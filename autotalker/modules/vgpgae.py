"""
This module contains the Variational Gene Program Graph Autoencoder class, the 
neural network module that underlies the Autotalker model.
"""

from typing import Literal, Optional, Tuple, Union

import mlflow
import numpy as np
import torch
import torch.nn as nn
from torch_geometric.data import Data

from autotalker.nn import (DotProductGraphDecoder,
                           GraphEncoder,
                           MaskedGeneExprDecoder,
                           OneHopAttentionNodeLabelAggregator,
                           OneHopGCNNormNodeLabelAggregator,
                           OneHopSumNodeLabelAggregator,
                           SelfNodeLabelNoneAggregator)
from .basemodulemixin import BaseModuleMixin
from .losses import (compute_addon_l1_reg_loss,
                     compute_edge_recon_loss,
                     compute_gene_expr_recon_nb_loss,
                     compute_gene_expr_recon_zinb_loss,
                     compute_group_lasso_reg_loss,
                     compute_kl_reg_loss)
from .vgaemodulemixin import VGAEModuleMixin


class VGPGAE(nn.Module, BaseModuleMixin, VGAEModuleMixin):
    """
    Variational Gene Program Graph Autoencoder class.

    Parameters
    ----------
    n_input:
        Number of nodes in the input layer.
    n_hidden_encoder:
        Number of nodes in the encoder hidden layer.
    n_nonaddon_gps:
        Number of nodes in the latent space (gene programs from the gene program
        mask).
    n_addon_gps:
        Number of add-on nodes in the latent space (de-novo gene programs).
    n_cond_embed:
        Number of conditional embedding nodes.
    n_output:
        Number of nodes in the output layer.
    n_genes_in_mask:
        Number of source and target genes that are included in the gp mask.
    gene_expr_decoder_mask:
        Gene program mask for the gene expression decoder.
    genes_idx:
        Index of genes in a concatenated vector of target and source genes that
        are in gps of the gp mask.
    conditions:
        Conditions used for the conditional embedding.
    conv_layer_encoder:
        Convolutional layer used in the graph encoder.
    encoder_n_attention_heads:
        Only relevant if ´conv_layer_encoder == gatv2conv´. Number of attention
        heads used.
    dropout_rate_encoder:
        Probability that nodes will be dropped in the encoder during training.
    dropout_rate_graph_decoder:
        Probability that nodes will be dropped in the graph decoder during 
        training.
    include_edge_recon_loss:
        If `True`, includes the redge reconstruction loss in the loss 
        optimization.
    include_gene_expr_recon_loss:
        If `True`, includes the gene expression reconstruction loss in the 
        loss optimization.
    gene_expr_recon_dist:
        The distribution used for gene expression reconstruction. If `nb`, uses
        a negative binomial distribution. If `zinb`, uses a zero-inflated
        negative binomial distribution.
    node_label_method:
        Node label method that will be used for gene expression reconstruction. 
        If ´self´, use only the input features of the node itself as node labels
        for gene expression reconstruction. If ´one-hop-sum´, use a 
        concatenation of the node's input features with the sum of the input 
        features of all nodes in the node's one-hop neighborhood. If 
        ´one-hop-norm´, use a concatenation of the node`s input features with
        the node's one-hop neighbors input features normalized as per Kipf, T. 
        N. & Welling, M. Semi-Supervised Classification with Graph Convolutional
        Networks. arXiv [cs.LG] (2016). If ´one-hop-attention´, use a 
        concatenation of the node`s input features with the node's one-hop 
        neighbors input features weighted by an attention mechanism.
    active_gp_thresh_ratio:
        Ratio that determines which gene programs are considered active and are
        used for edge reconstruction. All inactive gene programs will be dropped
        out. Aggregations of the absolute values of the gene weights of the 
        gene expression decoder per gene program are calculated. The maximum 
        value, i.e. the value of the gene program with the highest aggregated 
        value will be used as a benchmark and all gene programs whose aggregated
        value is smaller than ´active_gp_thresh_ratio´ times this maximum value 
        will be set to inactive. If ´==0´, all gene programs will be considered
        active. More information can be found in ´self.get_active_gp_mask()´.
    log_variational:
        If ´True´, transforms x by log(x+1) prior to encoding for numerical 
        stability (not normalization).
    cond_embed_injection:
        Determines in which VGPGAE modules the conditional embedding is
        injected.
    """
    def __init__(self,
                 n_input: int,
                 n_hidden_encoder: int,
                 n_nonaddon_gps: int,
                 n_addon_gps: int,
                 n_cond_embed: int,
                 n_output: int,
                 gene_expr_decoder_mask: torch.Tensor,
                 genes_idx: torch.Tensor,
                 conditions: list=[],
                 conv_layer_encoder: Literal["gcnconv", "gatv2conv"]="gcnconv",
                 encoder_n_attention_heads: int=4,
                 dropout_rate_encoder: float=0.,
                 dropout_rate_graph_decoder: float=0.,
                 include_edge_recon_loss: bool=True,
                 include_gene_expr_recon_loss: bool=True,
                 gene_expr_recon_dist: Literal["nb", "zinb"]="nb",
                 node_label_method: Literal[
                    "self",
                    "one-hop-norm",
                    "one-hop-sum",
                    "one-hop-attention"]="one-hop-attention",
                 active_gp_thresh_ratio: float=1.,
                 log_variational: bool=True,
                 cond_embed_injection: Optional[list]=["encoder",
                                                       "gene_expr_decoder"]):
        super().__init__()
        self.n_input_ = n_input
        self.n_hidden_encoder_ = n_hidden_encoder
        self.n_nonaddon_gps_ = n_nonaddon_gps
        self.n_addon_gps_ = n_addon_gps
        self.n_cond_embed_ = n_cond_embed
        self.n_output_ = n_output
        self.conditions_ = conditions
        self.n_conditions_ = len(conditions)
        self.condition_label_encoder_ = {
            k: v for k, v in zip(conditions, range(len(conditions)))}
        self.conv_layer_encoder_ = conv_layer_encoder
        self.encoder_n_attention_heads_ = encoder_n_attention_heads
        self.dropout_rate_encoder_ = dropout_rate_encoder
        self.dropout_rate_graph_decoder_ = dropout_rate_graph_decoder
        self.include_edge_recon_loss_ = include_edge_recon_loss
        self.include_gene_expr_recon_loss_ = include_gene_expr_recon_loss
        self.gene_expr_recon_dist_ = gene_expr_recon_dist
        self.node_label_method_ = node_label_method
        self.active_gp_thresh_ratio_ = active_gp_thresh_ratio
        self.log_variational_ = log_variational
        self.cond_embed_injection_ = cond_embed_injection
        self.freeze_ = False

        print("--- INITIALIZING NEW NETWORK MODULE: VARIATIONAL GENE PROGRAM "
              "GRAPH AUTOENCODER ---")
        print(f"LOSS -> include_edge_recon_loss: {include_edge_recon_loss}, "
              f"include_gene_expr_recon_loss: {include_gene_expr_recon_loss}, "
              f"gene_expr_recon_dist: {gene_expr_recon_dist}")
        print(f"NODE LABEL METHOD -> {node_label_method}")
        print(f"ACTIVE GP THRESHOLD RATIO -> {active_gp_thresh_ratio}")
        print(f"LOG VARIATIONAL -> {log_variational}")
        print(f"CONDITIONAL EMBEDDING INJECTION -> {cond_embed_injection}")

        if (cond_embed_injection is not None) & (self.n_conditions_ > 0):
            self.cond_embedder = nn.Embedding(
                self.n_conditions_,
                n_cond_embed)

        self.encoder = GraphEncoder(
            n_input=n_input,
            n_cond_embed_input=(n_cond_embed if ("encoder" in 
                                self.cond_embed_injection_) &
                                (self.n_conditions_ != 0) else 0),
            n_hidden=n_hidden_encoder,
            n_latent=n_nonaddon_gps,
            n_addon_latent=n_addon_gps,
            conv_layer=conv_layer_encoder,
            n_attention_heads=encoder_n_attention_heads,
            dropout_rate=dropout_rate_encoder,
            activation=torch.relu)
        
        self.graph_decoder = DotProductGraphDecoder(
            dropout_rate=dropout_rate_graph_decoder)

        self.gene_expr_decoder = MaskedGeneExprDecoder(
            n_input=n_nonaddon_gps,
            n_addon_input=n_addon_gps,
            n_cond_embed_input=(n_cond_embed if ("gene_expr_decoder" in 
                                self.cond_embed_injection_) &
                                (self.n_conditions_ != 0) else 0),
            n_output=n_output,
            mask=gene_expr_decoder_mask,
            genes_idx=genes_idx,
            recon_dist=self.gene_expr_recon_dist_)

        if node_label_method == "self":
            self.gene_expr_node_label_aggregator = (
                SelfNodeLabelNoneAggregator(genes_idx=genes_idx))
        elif node_label_method == "one-hop-norm":
            self.gene_expr_node_label_aggregator = (
                OneHopGCNNormNodeLabelAggregator(genes_idx=genes_idx))
        elif node_label_method == "one-hop-sum":
            self.gene_expr_node_label_aggregator = (
                OneHopSumNodeLabelAggregator(genes_idx=genes_idx)) 
        elif node_label_method == "one-hop-attention": 
            self.gene_expr_node_label_aggregator = (
                OneHopAttentionNodeLabelAggregator(n_input=n_input,
                                                   genes_idx=genes_idx))
        
        # Gene-specific dispersion parameters
        self.theta = torch.nn.Parameter(torch.randn(len(genes_idx)))

    def forward(self,
                data_batch: Data,
                decoder: Literal["graph", "gene_expr"],
                use_only_active_gps: bool=False,
                conditions: Optional[int]=None) -> dict:
        """
        Forward pass of the VGPGAE module.

        Parameters
        ----------
        data_batch:
            PyG Data object containing either an edge-level batch if 
            ´decoder == graph´ or a node-level batch if ´decoder == gene_expr´.
        decoder:
            Decoder to use for the forward pass, either ´graph´ for edge
            reconstruction or ´gene_expr´ for gene expression reconstruction.
        use_only_active_gps:
            Only relevant if ´decoder == graph´. If ´True´, use only active gene
            programs for edge reconstruction.
        conditions:
            Label encoding of the conditions.

        Returns
        ----------
        output:
            Dictionary containing reconstructed adjacency matrix logits if
            ´decoder == graph´ or the parameters of the gene expression 
            distribution if ´decoder == gene_expr´, as well as ´mu´ and ´logstd´ 
            from the latent space distribution.
        """
        if (self.cond_embed_injection_ is not None) & (self.n_conditions_ > 0):
            cond_embed = self.cond_embedder(conditions)
        else:
            cond_embed = None

        x = data_batch.x # dim: n_obs x n_genes
        edge_index = data_batch.edge_index # dim 2 x n_edges
        output = {}
        # Use observed library size as scaling factor for the negative binomial 
        # means of the gene expression distribution
        self.log_library_size = torch.log(x.sum(1)).unsqueeze(1)
        
        # Convert gene expression for numerical stability
        if self.log_variational_:
            x_enc = torch.log(1 + x)
        else:
            x_enc = x

        # Use encoder to get latent distribution parameters and latent features
        self.mu, self.logstd = self.encoder(
            x=x_enc,
            edge_index=edge_index,
            cond_embed=(cond_embed if "encoder" in self.cond_embed_injection_
                        else None))
        output["mu"] = self.mu
        output["logstd"] = self.logstd
        z = self.reparameterize(self.mu, self.logstd)

        # Only retain active gene programs
        if use_only_active_gps:
            active_gp_mask = self.get_active_gp_mask()
            z[:, ~active_gp_mask] = 0

        # Use decoder to get either the reconstructed adjacency matrix logits
        # or the gene expression parameters
        if decoder == "graph":
            output["adj_recon_logits"] = self.graph_decoder(z=z)
        elif decoder == "gene_expr":
            # Compute aggregated neighborhood gene expression for gene
            # expression reconstruction
            output["node_labels"] = self.gene_expr_node_label_aggregator(
                x=x, 
                edge_index=edge_index,
                batch_size=data_batch.batch_size)

            output["gene_expr_dist_params"] = self.gene_expr_decoder(
                z=z[:data_batch.batch_size],
                log_library_size=self.log_library_size[:data_batch.batch_size],
                cond_embed=(cond_embed[:data_batch.batch_size] if (cond_embed is
                            not None) & ("gene_expr_decoder" in
                            self.cond_embed_injection_) else None))
        return output

    def loss(self,
             edge_data_batch: Data,
             edge_model_output: dict,
             node_model_output: dict,
             lambda_l1_addon: float,
             lambda_group_lasso: float,
             lambda_gene_expr_recon: float=1.0,
             lambda_edge_recon: Optional[float]=None,
             edge_recon_active: bool=True) -> dict:
        """
        Calculate the optimization loss for backpropagation as well as the 
        global loss that also contains components omitted from optimization 
        (not backpropagated).

        Parameters
        ----------
        edge_data_batch:
            PyG Data object containing an edge-level batch.
        edge_model_output:
            Output of the edge-level forward pass for edge reconstruction.
        node_model_output:
            Output of the node-level forward pass for gene expression 
            reconstruction.
        lambda_edge_recon:
            Lambda (weighting factor) for the edge reconstruction loss. If ´>0´,
            this will enforce gene programs to be meaningful for edge
            reconstruction and, hence, to preserve spatial colocalization
            information.
        lambda_gene_expr_recon:
            Lambda (weighting factor) for the gene expression reconstruction
            loss. If ´>0´, this will enforce interpretable gene programs that
            can be combined in a linear way to reconstruct gene expression.
        lambda_group_lasso:
            Lambda (weighting factor) for the group lasso regularization loss of
            gene programs. If ´>0´, this will enforce sparsity of gene programs.
        lambda_l1_addon:
            Lambda (weighting factor) for the L1 regularization loss of genes in
            addon gene programs. If ´>0´, this will enforce sparsity of genes in
            addon gene programs.
        edge_recon_active:
            If ´True´, includes the edge reconstruction loss in the optimization
            / backpropagation. Setting this to ´False´ at the beginning of model
            training allows pretraining of the gene expression decoder.

        Returns
        ----------
        loss_dict:
            Dictionary containing the loss used for backpropagation 
            (loss_dict["optim_loss"]), which consists of all loss components 
            used for optimization, the global loss (loss_dict["global_loss"]), 
            which contains all loss components irrespective of whether they are
            used for optimization (needed as metric for early stopping and best
            model saving), as well as all individual loss components that 
            contribute to the global loss.
        """
        loss_dict = {}

        # If not specified explicitly, compute edge reconstruction loss 
        # weighting factor based on number of possible edges and negative edges
        if lambda_edge_recon is None:
            n_possible_edges = edge_data_batch.x.shape[0] ** 2
            n_neg_edges = n_possible_edges - edge_data_batch.edge_index.shape[1]
            lambda_edge_recon = n_possible_edges / (n_neg_edges * 2)

        # Compute Kullback-Leibler divergence loss
        loss_dict["kl_reg_loss"] = compute_kl_reg_loss(
            mu=edge_model_output["mu"],
            logstd=edge_model_output["logstd"],
            n_nodes=edge_data_batch.x.size(0))

        # Compute edge reconstruction binary cross entropy loss
        loss_dict["edge_recon_loss"] = (lambda_edge_recon * 
        compute_edge_recon_loss(
            adj_recon_logits=edge_model_output["adj_recon_logits"],
            edge_labels=edge_data_batch.edge_label,
            edge_label_index=edge_data_batch.edge_label_index))

        # Compute gene expression reconstruction negative binomial or
        # zero-inflated negative binomial loss
        theta = torch.exp(self.theta) # gene-specific inverse dispersion
        if self.gene_expr_recon_dist_ == "nb":
            nb_means = node_model_output["gene_expr_dist_params"]
            loss_dict["gene_expr_recon_loss"] = (lambda_gene_expr_recon * 
            compute_gene_expr_recon_nb_loss(
                    x=node_model_output["node_labels"],
                    mu=nb_means,
                    theta=theta))
        elif self.gene_expr_recon_dist_ == "zinb":
            nb_means, zi_prob_logits = (
                node_model_output["gene_expr_dist_params"])
            loss_dict["gene_expr_recon_loss"] = (lambda_gene_expr_recon * 
            compute_gene_expr_recon_zinb_loss(
                    x=node_model_output["node_labels"],
                    mu=nb_means,
                    theta=theta,
                    zi_prob_logits=zi_prob_logits))

        # Compute group lasso regularization loss of gene programs
        loss_dict["group_lasso_reg_loss"] = (lambda_group_lasso * 
        compute_group_lasso_reg_loss(self.named_parameters()))

        # Compute l1 regularization loss of genes in addon gene programs
        if self.n_addon_gps_ != 0:
            loss_dict["addon_gp_l1_reg_loss"] = (lambda_l1_addon * 
            compute_addon_l1_reg_loss(self.named_parameters()))

        # Compute optimization loss used for backpropagation as well as global
        # loss used for early stopping of model training and best model saving
        loss_dict["global_loss"] = 0
        loss_dict["optim_loss"] = 0
        loss_dict["global_loss"] += loss_dict["kl_reg_loss"]
        loss_dict["optim_loss"] += loss_dict["kl_reg_loss"]
        if self.include_edge_recon_loss_:
            loss_dict["global_loss"] += loss_dict["edge_recon_loss"]
            if edge_recon_active:
                loss_dict["optim_loss"] += loss_dict["edge_recon_loss"]
        if self.include_gene_expr_recon_loss_:
            loss_dict["global_loss"] += loss_dict["gene_expr_recon_loss"]
            loss_dict["optim_loss"] += loss_dict["gene_expr_recon_loss"]
            loss_dict["global_loss"] += loss_dict["group_lasso_reg_loss"]
            loss_dict["optim_loss"] += loss_dict["group_lasso_reg_loss"]
            if self.n_addon_gps_ != 0:
                loss_dict["global_loss"] += loss_dict["addon_gp_l1_reg_loss"]
                loss_dict["optim_loss"] += loss_dict["addon_gp_l1_reg_loss"]
        return loss_dict

    def get_gp_weights(self) -> torch.Tensor:
        """
        Get the gene weights of the gene expression negative binomial means 
        decoder.

        Returns:
        ----------
        gp_weights:
            Tensor containing the gene expression decoder gene weights.
        """
        # Get gp gene expression decoder gene weights
        gp_weights = (self.gene_expr_decoder.nb_means_normalized_decoder
                      .masked_l.weight.data).clone()
        if self.n_addon_gps_ > 0:
            gp_weights = torch.cat(
                [gp_weights, 
                 (self.gene_expr_decoder.nb_means_normalized_decoder.addon_l
                  .weight.data).clone()], axis=1)
        return gp_weights


    def get_active_gp_mask(
            self,
            abs_gp_weights_agg_mode: Literal["sum",
                                             "nzmeans",
                                             "sum+nzmeans"]="sum+nzmeans",
            return_gp_weights: bool=False
            ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """
        Get a mask of active gene programs based on the gene expression decoder
        gene weights of gene programs. Active gene programs are gene programs
        whose absolute gene weights aggregated over all genes are greater than 
        ´self.active_gp_thresh_ratio_´ times the absolute gene weights
        aggregation of the gene program with the maximum value across all gene 
        programs. Depending on ´abs_gp_weights_agg_mode´, the aggregation will 
        be either a sum of absolute gene weights (prioritizes gene programs that
        reconstruct many genes) or a mean of non-zero absolute gene weights 
        (normalizes for the number of genes that a gene program reconstructs) or
        a combination of the two.

        Parameters
        ----------
        abs_gp_weights_agg_mode:
            If ´sum´, uses sums of absolute gp weights for aggregation and
            active gp determination. If ´nzmeans´, uses means of non-zero 
            absolute gp weights for aggregation and active gp determination. If
            ´sum+nzmeans´, uses a combination of sums and means of non-zero
            absolute gp weights for aggregation and active gp determination.
        return_gp_weights:
            If ´True´, in addition return the gene expression decoder gene 
            weights of the active gene programs.

        Returns
        ----------
        active_gp_mask:
            Boolean tensor of gene programs which contains `True` for active
            gene programs and `False` for inactive gene programs.
        active_gp_weights:
            Tensor containing the gene expression decoder gene weights of active
            gene programs.
        """
        gp_weights = self.get_gp_weights()

        # Correct gp weights for zero inflation using zero inflation 
        # probabilities over all observations if zinb distribution is used to 
        # model gene expression
        if self.gene_expr_recon_dist_ == "zinb":
            _, zi_probs = self.get_gene_expr_dist_params(
                z=self.mu,
                log_library_size=self.log_library_size)
            non_zi_probs = 1 - zi_probs
            non_zi_probs_sum = non_zi_probs.sum(0).unsqueeze(1) # sum over obs 
            gp_weights *= non_zi_probs_sum 

        # Aggregate absolute gp weights based on ´abs_gp_weights_agg_mode´ and 
        # calculate thresholds of aggregated absolute gp weights and get active
        # gp mask and (optionally) active gp weights
        abs_gp_weights_sums = gp_weights.norm(p=1, dim=0)
        if abs_gp_weights_agg_mode in ["sum", "sum+nzmeans"]:
            max_abs_gp_weights_sum = max(abs_gp_weights_sums)
            min_abs_gp_weights_sum_thresh = (self.active_gp_thresh_ratio_ * 
                                             max_abs_gp_weights_sum)
            active_gp_mask = (abs_gp_weights_sums >= 
                              min_abs_gp_weights_sum_thresh)
        if abs_gp_weights_agg_mode in ["nzmeans", "sum+nzmeans"]:
            abs_gp_weights_nzmeans = (abs_gp_weights_sums / 
                                      torch.count_nonzero(gp_weights, dim=0))
            max_abs_gp_weights_nzmean = max(abs_gp_weights_nzmeans)
            min_abs_gp_weights_nzmean_thresh = (self.active_gp_thresh_ratio_ * 
                                                max_abs_gp_weights_nzmean)
            if abs_gp_weights_agg_mode == "nzmeans":
                active_gp_mask = (abs_gp_weights_nzmeans >= 
                                  min_abs_gp_weights_nzmean_thresh)
            elif abs_gp_weights_agg_mode == "sum+nzmeans":
                # Combine active gp mask
                active_gp_mask = active_gp_mask | (abs_gp_weights_nzmeans >= 
                                 min_abs_gp_weights_nzmean_thresh)
        if return_gp_weights:
            active_gp_weights = gp_weights[:, active_gp_mask]
            return active_gp_mask, active_gp_weights
        else:
            return active_gp_mask

    def log_module_hyperparams_to_mlflow(self):
        """Log module hyperparameters to Mlflow."""
        for attr, attr_value in self._get_public_attributes().items():
            mlflow.log_param(attr, attr_value)

    def get_latent_representation(
            self,
            x: torch.Tensor,
            edge_index: torch.Tensor,
            conditions: Optional[torch.Tensor]=None,
            only_active_gps: bool=True,
            return_mu_std: bool=False
            ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """
        Encode input features ´x´ and ´edge_index´ into the latent distribution
        parameters and return either the distribution parameters themselves or
        latent features ´z´.
           
        Parameters
        ----------
        x:
            Feature matrix to be encoded into latent space (dim: n_obs x 
            n_genes).
        edge_index:
            Edge index of the graph (dim: 2, n_edges).
        conditions:
            Conditions for the conditional embedding.
        only_active_gps:
            If ´True´, return only the latent representation of active gps.
        return_mu_std:
            If ´True´, return ´mu´ and ´std´ instead of latent features ´z´.

        Returns
        -------
        z:
            Latent space features (dim: n_obs, n_active_gps).
        mu:
            Expected values of the latent posterior (dim: n_obs, n_active_gps).
        std:
            Standard deviations of the latent posterior (dim: n_obs, 
            n_active_gps).
        """
        # Get conditional embeddings
        if (self.cond_embed_injection_ is not None) & (self.n_conditions_ > 0):
            cond_embed = self.cond_embedder(conditions)
        else:
            cond_embed = None
            
        # Get latent distribution parameters
        mu, logstd = self.encoder(x=x,
                                  edge_index=edge_index,
                                  cond_embed=cond_embed)

        if only_active_gps:
            # Filter to active gene programs only
            active_gp_mask = self.get_active_gp_mask()
            mu, logstd = mu[:, active_gp_mask], logstd[:, active_gp_mask]

        if return_mu_std:
            std = torch.exp(logstd)
            return mu, std
        else:
            # Sample latent features from the latent normal distribution if in 
            # training mode or return ´mu´ if not in training mode
            z = self.reparameterize(mu, logstd)
            return z

    def get_gene_expr_dist_params(
            self,
            z: torch.Tensor,
            log_library_size: torch.Tensor
            ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """
        Decode latent features ´z´ to return the parameters of the distribution
        used for gene expression reconstruction (either (´nb_means´, ´zi_probs´)
        if a zero-inflated negative binomial is used or ´nb_means´ if a negative
        binomial is used).

        Parameters
        ----------
        z:
            Tensor containing the latent features / gene program scores (dim: 
            n_obs x n_gps).
        log_library_size:
            Tensor containing the log library size of the observations / cells 
            (dim: n_obs x 1).

        Returns
        ----------
        nb_means:
            Expected values of the negative binomial distribution (dim: n_obs x
            n_genes).
        zi_probs:
            Zero-inflation probabilities of the zero-inflated negative binomial
            distribution (dim: n_obs x n_genes).
        """
        if self.gene_expr_recon_dist_ == "nb":
            nb_means = self.gene_expr_decoder(z=z,
                                              log_library_size=log_library_size)
            nb_means
            return nb_means
        if self.gene_expr_recon_dist_ == "zinb":
            nb_means, zi_prob_logits = self.gene_expr_decoder(
                z=z,
                log_library_size=log_library_size)
            zi_probs = torch.sigmoid(zi_prob_logits)
            return nb_means, zi_probs