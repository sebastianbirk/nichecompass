"""
This module contains the NicheCompass model. Different analysis capabilities are
integrated directly into the model API for easy use.
"""

from typing import Literal, List, Optional, Tuple, Union

import mlflow
import numpy as np
import pandas as pd
import scanpy as sc
import scipy.sparse as sp
import torch
from anndata import AnnData
from scipy.special import erfc

from nichecompass.data import (initialize_dataloaders,
                             prepare_data,
                             SpatialAnnTorchDataset)
from nichecompass.modules import VGPGAE
from nichecompass.train import Trainer
from .basemodelmixin import BaseModelMixin


class NicheCompass(BaseModelMixin):
    """
    NicheCompass model class.

    Parameters
    ----------
    adata:
        AnnData object with gene expression raw counts stored in
        ´adata.layers[counts_key]´ or ´adata.X´, depending on ´counts_key´,
        sparse adjacency matrix stored in ´adata.obsp[adj_key]´, gene program
        names stored in ´adata.uns[gp_names_key]´, and binary gene program
        targets and sources masks stored in ´adata.varm[gp_targets_mask_key]´
        and ´adata.varm[gp_sources_mask_key]´ respectively.
    adata_atac:
        Optional AnnData object with paired spatial chromatin accessibility
        raw counts stored in ´adata_atac.X´, and sparse boolean chromatin
        accessibility targets and sources masks stored in
        ´adata_atac.varm[ca_targets_mask_key]´ and
        ´adata_atac.varm[ca_sources_mask_key]´ respectively.
    counts_key:
        Key under which the gene expression raw counts are stored in
        ´adata.layer´. If ´None´, uses ´adata.X´ as counts. 
    adj_key:
        Key under which the sparse adjacency matrix is stored in ´adata.obsp´.
    gp_names_key:
        Key under which the gene program names are stored in ´adata.uns´.
    active_gp_names_key:
        Key under which the active gene program names will be stored in 
        ´adata.uns´.
    gp_targets_mask_key:
        Key under which the gene program targets mask is stored in ´adata.varm´.
    gp_sources_mask_key:
        Key under which the gene program sources mask is stored in ´adata.varm´.
    ca_targets_mask_key:
        Key under which the chromatin accessibility targets mask is stored in
        ´adata_atac.varm´.
    ca_sources_mask_key:
        Key under which the chromatin accessibility sources mask is stored in
        ´adata_atac.varm´.
    latent_key:
        Key under which the latent / gene program representation of active gene
        programs will be stored in ´adata.obsm´ after model training.
    condition_key:
        Key under which the conditions are stored in ´adata.obs´.
    cond_embed_key:
        Key under which the conditional embeddings will be stored in
        ´adata.uns´.
    cond_embed_injection:
        List of VGPGAE modules in which the conditional embedding is injected.
    genes_idx_key:
        Key in ´adata.uns´ where the index of a concatenated vector of target
        and source genes that are in the gene program masks are stored.    
    target_genes_idx_key:
        Key in ´adata.uns´ where the index of target genes that are in the gene
        program masks are stored.
    source_genes_idx_key:
        Key in ´adata.uns´ where the index of source genes that are in the gene
        program masks are stored.
    peaks_idx_key:
        Key in ´adata_atac.uns´ where the index of a concatenated vector of
        target and source peaks that are in the chromatin accessibility masks
        are stored.          
    target_peaks_idx_key:
        Key in ´adata_atac.uns´ where the index of target peaks that are in the
        chromatin accessibility masks are stored.
    source_peaks_idx_key:
        Key in ´adata_atac.uns´ where the index of source peaks that are in the
        chromatin accessibility masks are stored.
    recon_adj_key:
        Key in ´adata.obsp´ where the reconstructed adjacency matrix edge
        probabilities will be stored.
    agg_alpha_key:
        Key in ´adata.obsp´ where the attention weights of the gene expression
        node label aggregator will be stored.
    include_edge_recon_loss:
        If `True`, includes the edge reconstruction loss in the backpropagation.
    include_gene_expr_recon_loss:
        If `True`, includes the gene expression reconstruction loss in the
        backpropagation.
    include_chrom_access_recon_loss:
        If `True`, includes the chromatin accessibility reconstruction loss in
        the backpropagation.
    include_cond_contrastive_loss:
        If `True`, includes the conditional contrastive loss in the
        backpropagation.
    gene_expr_recon_dist:
        The distribution used for gene expression reconstruction. If `nb`, uses
        a negative binomial distribution. If `zinb`, uses a zero-inflated
        negative binomial distribution.
    log_variational:
        If ´True´, transforms x by log(x+1) prior to encoding for numerical 
        stability (not for normalization).
    node_label_method:
        Node label method that will be used for omics reconstruction. If ´self´,
        uses only the input features of the node itself as node labels for omics
        reconstruction. If ´one-hop-sum´, uses a concatenation of the node's
        input features with the sum of the input features of all nodes in the
        node's one-hop neighborhood. If ´one-hop-norm´, uses a concatenation of
        the node`s input features with the node's one-hop neighbors input
        features normalized as per Kipf, T. N. & Welling, M. Semi-Supervised
        Classification with Graph Convolutional Networks. arXiv [cs.LG] (2016).
        If ´one-hop-attention´, uses a concatenation of the node`s input
        features with the node's one-hop neighbors input features weighted by an
        attention mechanism.
    active_gp_thresh_ratio:
        Ratio that determines which gene programs are considered active and are
        used in the latent representation after model training. All inactive
        gene programs will be dropped during model training after a determined
        number of epochs. Aggregations of the absolute values of the gene
        weights of the gene expression decoder per gene program are calculated.
        The maximum value, i.e. the value of the gene program with the highest
        aggregated value will be used as a benchmark and all gene programs whose
        aggregated value is smaller than ´active_gp_thresh_ratio´ times this
        maximum value will be set to inactive. If ´==0´, all gene programs will
        be considered active. More information can be found in 
        ´self.model.get_active_gp_mask()´.
    n_layers_encoder:
        Number of GNN layers in the encoder.
    n_hidden_encoder:
        Number of nodes in the encoder hidden layers. If ´None´ is determined
        automatically based on the number of input genes and gene programs.
    conv_layer_encoder:
        Convolutional layer used as GNN in the encoder.
    encoder_n_attention_heads:
        Only relevant if ´conv_layer_encoder == gatv2conv´. Number of attention
        heads used in the GNN layers of the encoder.
    dropout_rate_encoder:
        Probability that nodes will be dropped in the encoder during training.
    dropout_rate_graph_decoder:
        Probability that nodes will be dropped in the graph decoder during 
        training.
    conditions:
        Condition names to get the right encoding when used after reloading.
    n_addon_gps:
        Number of addon gene programs (i.e. gene programs that are not included
        in masks but can be learned de novo).
    n_cond_embed:
        Number of conditional embedding nodes.
    kwargs:
        NicheCompass kwargs (to support legacy versions).
    """
    def __init__(self,
                 adata: AnnData,
                 adata_atac: Optional[AnnData]=None,
                 counts_key: Optional[str]="counts",
                 adj_key: str="spatial_connectivities",
                 gp_names_key: str="nichecompass_gp_names",
                 active_gp_names_key: str="nichecompass_active_gp_names",
                 gp_targets_mask_key: str="nichecompass_gp_targets",
                 gp_sources_mask_key: str="nichecompass_gp_sources",
                 ca_targets_mask_key: Optional[str]="nichecompass_ca_targets",
                 ca_sources_mask_key: Optional[str]="nichecompass_ca_sources",
                 latent_key: str="nichecompass_latent",
                 condition_key: Optional[str]=None,
                 cond_embed_key: Optional[str]="nichecompass_cond_embed",
                 cond_embed_injection: Optional[List]=["gene_expr_decoder",
                                                       "chrom_access_decoder"],
                 genes_idx_key: str="nichecompass_genes_idx",
                 target_genes_idx_key: str="nichecompass_target_genes_idx",
                 source_genes_idx_key: str="nichecompass_source_genes_idx",
                 peaks_idx_key: str="nichecompass_peaks_idx",
                 target_peaks_idx_key: str="nichecompass_target_peaks_idx",
                 source_peaks_idx_key: str="nichecompass_source_peaks_idx",
                 recon_adj_key: Optional[str]="nichecompass_recon_connectivities",
                 agg_alpha_key: Optional[str]="nichecompass_agg_alpha",
                 include_edge_recon_loss: bool=True,
                 include_gene_expr_recon_loss: bool=True,
                 include_chrom_access_recon_loss: Optional[bool]=True,
                 include_cond_contrastive_loss: bool=True,
                 gene_expr_recon_dist: Literal["nb", "zinb"]="nb",
                 log_variational: bool=True,
                 node_label_method: Literal[
                    "self",
                    "one-hop-sum",
                    "one-hop-norm",
                    "one-hop-attention"]="one-hop-attention",
                 active_gp_thresh_ratio: float=0.05,
                 n_layers_encoder: int=1,
                 n_hidden_encoder: Optional[int]=None,
                 conv_layer_encoder: Literal["gcnconv", "gatv2conv"]="gcnconv",
                 encoder_n_attention_heads: Optional[int]=4,
                 dropout_rate_encoder: float=0.,
                 dropout_rate_graph_decoder: float=0.,
                 conditions: Optional[list]=None, 
                 n_addon_gps: int=0,
                 n_cond_embed: Optional[int]=None,
                 **kwargs):
        self.adata = adata
        self.adata_atac = adata_atac

        self.counts_key_ = counts_key
        self.adj_key_ = adj_key
        self.gp_names_key_ = gp_names_key
        self.active_gp_names_key_ = active_gp_names_key
        self.gp_targets_mask_key_ = gp_targets_mask_key
        self.gp_sources_mask_key_ = gp_sources_mask_key
        self.ca_targets_mask_key_ = ca_targets_mask_key
        self.ca_sources_mask_key_ = ca_sources_mask_key
        self.latent_key_ = latent_key
        self.condition_key_ = condition_key
        self.cond_embed_key_ = cond_embed_key
        self.cond_embed_injection_ = cond_embed_injection
        self.genes_idx_key_ = genes_idx_key
        self.target_genes_idx_key_ = target_genes_idx_key
        self.source_genes_idx_key_ = source_genes_idx_key
        self.peaks_idx_key_ = peaks_idx_key
        self.target_peaks_idx_key_ = target_peaks_idx_key
        self.source_peaks_idx_key_ = source_peaks_idx_key
        self.recon_adj_key_ = recon_adj_key
        self.agg_alpha_key_ = agg_alpha_key
        self.include_edge_recon_loss_ = include_edge_recon_loss
        self.include_gene_expr_recon_loss_ = include_gene_expr_recon_loss
        self.include_chrom_access_recon_loss_ = include_chrom_access_recon_loss
        self.include_cond_contrastive_loss_ = include_cond_contrastive_loss
        self.gene_expr_recon_dist_ = gene_expr_recon_dist
        self.log_variational_ = log_variational
        self.node_label_method_ = node_label_method
        self.active_gp_thresh_ratio_ = active_gp_thresh_ratio

        # Retrieve gene program masks
        if gp_targets_mask_key in adata.varm:
            gp_targets_mask = adata.varm[gp_targets_mask_key].T
        else:
            raise ValueError("Please specify an adequate ´gp_targets_mask_key´ "
                             "for your adata object. The targets mask needs to "
                             "be stored in ´adata.varm[gp_targets_mask_key]´. "
                             " If you do not want to mask gene expression "
                             "reconstruction, you can create a mask of 1s that"
                             " allows all gene program latent nodes to "
                             "reconstruct all genes.")
        # NOTE: dtype can be changed to bool and should be able to handle sparse
        # mask
        self.gp_mask_ = torch.tensor(gp_targets_mask, dtype=torch.float32)
        if node_label_method != "self":
            if gp_sources_mask_key in adata.varm:
                gp_sources_mask = adata.varm[gp_sources_mask_key].T
            else:
                raise ValueError("Please specify an adequate "
                                 "´gp_sources_mask_key´ for your adata object. "
                                 "The sources mask needs to be stored in "
                                 "´adata.varm[gp_sources_mask_key]´. If you do "
                                 "not want to mask gene expression "
                                 "reconstruction, you can create a mask of 1s "
                                 " that allows all gene program latent nodes to"
                                 " reconstruct all genes.")
            # Horizontally concatenate targets and sources masks
            # NOTE: dtype can be changed to bool and should be able to handle
            # sparse mask
            self.gp_mask_ = torch.cat(
                (self.gp_mask_, torch.tensor(gp_sources_mask, 
                dtype=torch.float32)), dim=1)
        
        # Retrieve chromatin accessibility masks
        if adata_atac is None:
            self.ca_mask_ = None
        else:
            if ca_targets_mask_key in adata_atac.varm:
                ca_targets_mask = adata_atac.varm[ca_targets_mask_key].T.tocoo()
            else:
                raise ValueError("Please specify an adequate "
                                 "´ca_targets_mask_key´ for your adata_atac "
                                 "object. The targets mask needs to be stored "
                                 "in ´adata_atac.varm[ca_targets_mask_key]´. If"
                                 " you do not want to mask chromatin "
                                 " accessibility reconstruction, you can create"
                                 " a mask of 1s that allows all gene program "
                                 "latent nodes to reconstruct all peaks.")
            self.ca_mask_ = torch.sparse_coo_tensor(
                indices=[ca_targets_mask.row, ca_targets_mask.col],
                values=ca_targets_mask.data,
                size=ca_targets_mask.shape,
                dtype=torch.bool)
            if node_label_method != "self":
                if ca_sources_mask_key in adata_atac.varm:
                    ca_sources_mask = adata_atac.varm[
                        ca_sources_mask_key].T.tocoo()
                else:
                    raise ValueError("Please specify an adequate "
                                    "´ca_sources_mask_key´ for your adata_atac "
                                    "object. The sources mask needs to be "
                                    "stored in "
                                    "´adata_atac.varm[ca_sources_mask_key]´. If"
                                    "you do not want to mask chromatin "
                                    " accessibility reconstruction, you can "
                                    "create a mask of 1s that allows all gene "
                                    "program latent nodes to reconstruct all "
                                    "peaks.")
                # Horizontally concatenate targets and sources masks
                ca_combined_mask_row = np.concatenate(
                    (ca_targets_mask.row, ca_sources_mask.row), axis=0)
                ca_combined_mask_col = np.concatenate(
                    (ca_targets_mask.col, (ca_sources_mask.col + 
                                           ca_targets_mask.shape[1])), axis=0)
                ca_combined_mask_data = np.concatenate(
                    (ca_targets_mask.data, ca_sources_mask.data), axis=0)
                self.ca_mask_ = torch.sparse_coo_tensor(
                    indices=[ca_combined_mask_row, ca_combined_mask_col],
                    values=ca_combined_mask_data,
                    size=(ca_targets_mask.shape[0],
                          (ca_targets_mask.shape[1] + 
                           ca_sources_mask.shape[1])),
                    dtype=torch.bool)
                
        # Retrieve index of genes in gp mask
        self.genes_idx_ = adata.uns[genes_idx_key]
        self.target_genes_idx_ = adata.uns[target_genes_idx_key]
        self.source_genes_idx_ = adata.uns[source_genes_idx_key]

        # Retrieve index of peaks in ca mask
        if adata_atac is not None:
            self.peaks_idx_ = adata_atac.uns[peaks_idx_key]
            self.target_peaks_idx_ = adata_atac.uns[target_peaks_idx_key]
            self.source_peaks_idx_ = adata_atac.uns[source_peaks_idx_key]
        else:
            self.peaks_idx_ = None
            self.target_peaks_idx_ = None
            self.source_peaks_idx_ = None

        # Determine VGPGAE inputs
        self.n_input_ = adata.n_vars
        self.n_output_genes_ = adata.n_vars
        if node_label_method != "self":
            # Target and source genes are concatenated in output
            self.n_output_genes_ *= 2
        if adata_atac is not None:
            self.modalities_ = ["gene_expr", "chrom_access"]
            if not np.all(adata.obs.index == adata_atac.obs.index):
                raise ValueError("Please make sure that 'adata' and "
                                 "'adata_atac' contain the same observations in"
                                 " the same order.")
            # Peaks are concatenated to genes in input
            self.n_input_ += adata_atac.n_vars
            self.n_output_peaks_ = adata_atac.n_vars
            if node_label_method != "self":
                # Target and source peaks are concatenated in output
                self.n_output_peaks_ *= 2
        else:
            self.modalities_ = ["gene_expr"]
            self.n_output_peaks_ = 0
        self.n_layers_encoder_ = n_layers_encoder
        self.conv_layer_encoder_ = conv_layer_encoder
        if conv_layer_encoder == "gatv2conv":
            self.encoder_n_attention_heads_ = encoder_n_attention_heads
        else:
            self.encoder_n_attention_heads_ = 0
        self.dropout_rate_encoder_ = dropout_rate_encoder
        self.dropout_rate_graph_decoder_ = dropout_rate_graph_decoder
        self.n_nonaddon_gps_ = len(self.gp_mask_)
        self.n_addon_gps_ = n_addon_gps

        # Determine dimensionality of conditional embedding if not provided
        if n_cond_embed is None:
            n_cond_embed = self.n_nonaddon_gps_
        self.n_cond_embed_ = n_cond_embed

        # Determine dimensionality of hidden encoder layer if not provided
        if n_hidden_encoder is None:
            n_hidden_encoder = self.n_nonaddon_gps_
        self.n_hidden_encoder_ = n_hidden_encoder

        # Retrieve conditions
        if conditions is None:
            if condition_key is not None:
                self.conditions_ = adata.obs[condition_key].unique().tolist()
            else:
                self.conditions_ = []
        else:
            self.conditions_ = conditions
        
        # Validate counts layer key and counts values
        if counts_key is not None and counts_key not in adata.layers:
            raise ValueError("Please specify an adequate ´counts_key´. By "
                             "default the counts are assumed to be stored in "
                             "data.layers['counts'].")
        if include_gene_expr_recon_loss and log_variational:
            if counts_key is None:
                x = adata.X
            else:
                x = adata.layers[counts_key]
            if (x < 0).sum() > 0:
                raise ValueError("Please make sure that "
                                 "´adata.layers[counts_key]´ contains the"
                                 " raw counts (not log library size "
                                 "normalized) if ´include_gene_expr_recon_loss´"
                                 " is ´True´ and ´log_variational´ is ´True´. "
                                 "If you want to use log library size "
                                 " normalized counts, make sure that "
                                 "´log_variational´ is ´False´.")

        # Validate adjacency key
        if adj_key not in adata.obsp:
            raise ValueError("Please specify an adequate ´adj_key´. "
                             "By default the adjacency matrix is assumed to be "
                             "stored in adata.obsm['spatial_connectivities'].")

        # Validate gp key
        if gp_names_key not in adata.uns:
            raise ValueError("Please specify an adequate ´gp_names_key´. "
                             "By default the gene program names are assumed to "
                             "be stored in adata.uns['nichecompass_gp_names'].")

        # Validate condition key
        if condition_key is not None and condition_key not in adata.obs:
            raise ValueError("Please specify an adequate ´condition_key´. "
                             "The conditions need to be stored in "
                             "adata.obs[condition_key].")
        
        # Initialize model with Variational Gene Program Graph Autoencoder 
        # neural network module
        self.model = VGPGAE(
            n_input=self.n_input_,
            n_layers_encoder=self.n_layers_encoder_,
            n_hidden_encoder=self.n_hidden_encoder_,
            n_nonaddon_gps=self.n_nonaddon_gps_,
            n_addon_gps=self.n_addon_gps_,
            n_cond_embed=self.n_cond_embed_,
            n_output_genes=self.n_output_genes_,
            n_output_peaks=self.n_output_peaks_,
            gene_expr_decoder_mask=self.gp_mask_,
            chrom_access_decoder_mask=self.ca_mask_,
            gene_expr_mask_idx=self.genes_idx_,
            target_gene_expr_mask_idx=self.target_genes_idx_,
            source_gene_expr_mask_idx=self.source_genes_idx_,
            chrom_access_mask_idx=self.peaks_idx_,
            target_chrom_access_mask_idx=self.target_peaks_idx_,
            source_chrom_access_mask_idx=self.source_peaks_idx_,
            conditions=self.conditions_,
            conv_layer_encoder=self.conv_layer_encoder_,
            encoder_n_attention_heads=self.encoder_n_attention_heads_,
            dropout_rate_encoder=self.dropout_rate_encoder_,
            dropout_rate_graph_decoder=self.dropout_rate_graph_decoder_,
            include_edge_recon_loss=self.include_edge_recon_loss_,
            include_gene_expr_recon_loss=self.include_gene_expr_recon_loss_,
            include_chrom_access_recon_loss=self.include_chrom_access_recon_loss_,
            include_cond_contrastive_loss=self.include_cond_contrastive_loss_,
            gene_expr_recon_dist=self.gene_expr_recon_dist_,
            node_label_method=self.node_label_method_,
            active_gp_thresh_ratio=self.active_gp_thresh_ratio_,
            log_variational=self.log_variational_,
            cond_embed_injection=self.cond_embed_injection_)

        self.is_trained_ = False

        # Store init params for saving and loading
        self.init_params_ = self._get_init_params(locals())

    def train(self,
              n_epochs: int=100,
              n_epochs_all_gps: int=25,
              n_epochs_no_edge_recon: int=0,
              n_epochs_no_cond_contrastive: int=5,
              lr: float=0.001,
              weight_decay: float=0.,
              lambda_edge_recon: Optional[float]=500000.,
              lambda_gene_expr_recon: float=100.,
              lambda_chrom_access_recon: float=10.,
              lambda_cond_contrastive: float=0.,
              contrastive_logits_ratio: float=0.125,
              lambda_group_lasso: float=0.,
              lambda_l1_masked: float=0.,
              min_gp_genes_l1_masked: int=4,
              lambda_l1_addon: float=0.,
              edge_val_ratio: float=0.1,
              node_val_ratio: float=0.1,
              edge_batch_size: int=256,
              node_batch_size: Optional[int]=None,
              mlflow_experiment_id: Optional[str]=None,
              retrieve_cond_embeddings: bool=False,
              retrieve_recon_edge_probs: bool=False,
              retrieve_att_weights: bool=False,
              use_cuda_if_available: bool=True,
              **trainer_kwargs):
        """
        Train the NicheCompass model.
        
        Parameters
        ----------
        n_epochs:
            Number of epochs.
        n_epochs_all_gps:
            Number of epochs during which all gene programs are used for model
            training. After that only active gene programs are retained.
        n_epochs_no_edge_recon:
            Number of epochs during which the edge reconstruction loss is
            excluded from backpropagation for pretraining using the other loss
            components.
        n_epochs_no_cond_contrastive:
            Number of epochs during which the conditional contrastive loss is
            excluded from backpropagation for pretraining using the other
            loss components.
        lr:
            Learning rate.
        weight_decay:
            Weight decay (L2 penalty).
        lambda_edge_recon:
            Lambda (weighting factor) for the edge reconstruction loss. If ´>0´,
            this will enforce gene programs to be meaningful for edge
            reconstruction and, hence, to preserve spatial colocalization
            information.
        lambda_gene_expr_recon:
            Lambda (weighting factor) for the gene expression reconstruction
            loss. If ´>0´, this will enforce interpretable gene programs that
            can be combined in a linear way to reconstruct gene expression.
        lambda_chrom_access_recon:
            Lambda (weighting factor) for the chromatin accessibility
            reconstruction loss. If ´>0´, this will enforce interpretable gene
            programs that can be combined in a linear way to reconstruct
            chromatin accessibility.
        lambda_cond_contrastive:
            Lambda (weighting factor) for the conditional contrastive loss. If
            ´>0´, this will enforce observations from different conditions with
            very similar latent representations to become more similar and 
            observations with different latent representations to become more
            different.
        contrastive_logits_ratio:
            Ratio for determining the contrastive logits for the conditional
            contrastive loss. The top (´contrastive_logits_ratio´ * 100)% logits
            of sampled negative edges with nodes from different conditions serve
            as positive labels for the contrastive loss and the bottom
            (´contrastive_logits_ratio´ * 100)% logits of sampled negative edges
            with nodes from different conditions serve as negative labels.
        lambda_group_lasso:
            Lambda (weighting factor) for the group lasso regularization loss of
            gene programs. If ´>0´, this will enforce sparsity of gene programs.
        lambda_l1_masked:
            Lambda (weighting factor) for the L1 regularization loss of genes in
            masked gene programs. If ´>0´, this will enforce sparsity of genes
            in masked gene programs.
        min_gp_genes_l1_masked:
            The minimum number of genes that need to be in a gene program for
            the L1 regularization loss to be applied to the gene program.
        lambda_l1_addon:
            Lambda (weighting factor) for the L1 regularization loss of genes in
            addon gene programs. If ´>0´, this will enforce sparsity of genes in
            addon gene programs.
        edge_val_ratio:
            Fraction of the data that is used as validation set on edge-level.
            The rest of the data will be used as training set on edge-level.
        node_val_ratio:
            Fraction of the data that is used as validation set on node-level.
            The rest of the data will be used as training set on node-level.
        edge_batch_size:
            Batch size for the edge-level dataloaders.
        node_batch_size:
            Batch size for the node-level dataloaders. If ´None´, is
            automatically determined based on ´edge_batch_size´.
        mlflow_experiment_id:
            ID of the Mlflow experiment used for tracking training parameters
            and metrics.
        retrieve_cond_embeddings:
            If ´True´, retrieve the conditional embeddings after model training
            is finished if multiple conditions are present.
        retrieve_recon_edge_probs:
            If ´True´, retrieve the reconstructed edge probabilities after model
            training is finished.
        retrieve_att_weights:
            If ´True´, retrieve the node label aggregation attention weights
            after model training is finished if ´one-hop-attention´ was used
            for node label aggregation.
        use_cuda_if_available:
            If `True`, use cuda if available.
        trainer_kwargs:
            Kwargs for the model Trainer.
        """
        self.trainer = Trainer(
            adata=self.adata,
            adata_atac=self.adata_atac,
            model=self.model,
            counts_key=self.counts_key_,
            adj_key=self.adj_key_,
            gp_targets_mask_key=self.gp_targets_mask_key_,
            gp_sources_mask_key=self.gp_sources_mask_key_,
            condition_key=self.condition_key_,
            edge_val_ratio=edge_val_ratio,
            node_val_ratio=node_val_ratio,
            edge_batch_size=edge_batch_size,
            node_batch_size=node_batch_size,
            use_cuda_if_available=use_cuda_if_available,
            **trainer_kwargs)

        self.trainer.train(
            n_epochs=n_epochs,
            n_epochs_no_edge_recon=n_epochs_no_edge_recon,
            n_epochs_no_cond_contrastive=n_epochs_no_cond_contrastive,
            n_epochs_all_gps=n_epochs_all_gps,
            lr=lr,
            weight_decay=weight_decay,
            lambda_edge_recon=lambda_edge_recon,
            lambda_gene_expr_recon=lambda_gene_expr_recon,
            lambda_chrom_access_recon=lambda_chrom_access_recon,
            lambda_cond_contrastive=lambda_cond_contrastive,
            contrastive_logits_ratio=contrastive_logits_ratio,
            lambda_group_lasso=lambda_group_lasso,
            lambda_l1_masked=lambda_l1_masked,
            min_gp_genes_l1_masked=min_gp_genes_l1_masked,
            lambda_l1_addon=lambda_l1_addon,
            mlflow_experiment_id=mlflow_experiment_id)
        
        self.node_batch_size_ = self.trainer.node_batch_size_
        
        self.is_trained_ = True

        self.adata.obsm[self.latent_key_], _ = self.get_latent_representation(
           adata=self.adata,
           counts_key=self.counts_key_,
           adj_key=self.adj_key_,
           condition_key=self.condition_key_,
           only_active_gps=True,
           return_mu_std=True,
           node_batch_size=self.node_batch_size_)
        
        self.adata.uns[self.active_gp_names_key_] = self.get_active_gps()

        if (len(self.conditions_) > 0) & retrieve_cond_embeddings:
            self.adata.uns[self.cond_embed_key_] = self.get_cond_embeddings()

        if retrieve_recon_edge_probs:
            self.adata.obsp[self.recon_adj_key_] = self.get_recon_edge_probs()

        if (self.node_label_method_ == "one-hop-attention") & (
        retrieve_att_weights):
            self.adata.obsp[self.agg_alpha_key_] = (
                self.get_gene_expr_agg_att_weights(
                    node_batch_size=self.node_batch_size_))

        if mlflow_experiment_id is not None:
            mlflow.log_metric("n_active_gps",
                              len(self.adata.uns[self.active_gp_names_key_]))

    def run_differential_gp_tests(
            self,
            cat_key: str,
            selected_cats: Optional[Union[str,list]]=None,
            comparison_cats: Union[str, list]="rest",
            selected_gps: Optional[Union[str,list]]=None,
            gp_scores_weight_normalization: bool=False,
            n_sample: int=10000,
            log_bayes_factor_thresh: float=2.3,
            key_added: str="nichecompass_differential_gp_test_results",
            seed: int=0,
            adata: Optional[AnnData]=None) -> list:
        """
        Run differential gene program tests by comparing gene program / latent
        scores between a category and specified comparison categories for all
        categories in ´selected_cats´ (by default all categories in
        ´adata.obs[cat_key]´). Enriched category gene programs are determined
        through the log Bayes Factor between the hypothesis h0 that the
        (normalized) gene program / latent scores of observations of the
        category under consideration (z0) are higher than the (normalized) gene
        program / latent scores of observations of the comparison categories
        (z1) versus the alternative hypothesis h1 that the (normalized) gene
        program / latent scores of observations of the comparison categories
        (z1) are higher or equal to the (normalized) gene program / latent
        scores of observations of the category under consideration (z0). The
        results of the differential tests including the log Bayes Factors for
        enriched category gene programs are stored in a pandas DataFrame under
        ´adata.uns[key_added]´. The DataFrame also stores p_h0, the probability
        that z0 > z1 and p_h1, the probability that z1 >= z0. The rows are
        ordered by the log Bayes Factor. In addition, the (normalized) gene
        program / latent scores of enriched gene programs across any of the
        categories are stored in ´adata.obs´.

        Parts of the implementation are adapted from Lotfollahi, M. et al.
        Biologically informed deep learning to query gene programs in
        single-cell atlases. Nat. Cell Biol. 25, 337–350 (2023);
        https://github.com/theislab/scarches/blob/master/scarches/models/expimap/expimap_model.py#L429
        (24.11.2022).

        Parameters
        ----------
        cat_key:
            Key under which the categories and comparison categories are stored
            in ´adata.obs´.
        selected_cats:
            List of category labels for which differential tests will be run. If
            ´None´, uses all category labels from ´adata.obs[cat_key]´.
        comparison_cats:
            Categories used as comparison group. If ´rest´, all categories other
            than the category under consideration are used as comparison group.
        selected_gps:
            List of gene program names for which differential tests will be run.
            If ´None´, uses all active gene programs.
        gp_scores_weight_normalization:
            If ´True´, normalize the gp scores by the nb means gene expression
            decoder weights. If ´False´, normalize the gp scores by the signs of
            the summed nb means gene expression decoder weights (this is only
            relevant with 'zinb' loss).
        n_sample:
            Number of observations to be drawn from the category and comparison
            categories for the log Bayes Factor computation.
        log_bayes_factor_thresh:
            Log bayes factor threshold. Category gene programs with a higher
            absolute score than this threshold are considered enriched.
        key_added:
            Key under which the test results pandas DataFrame is stored in
            ´adata.uns´.
        seed:
            Random seed for reproducible sampling.
        adata:
            AnnData object to be used. If ´None´, uses the adata object stored
            in the model instance.

        Returns
        ----------
        enriched_gps:
            Names of enriched gene programs across all categories (duplicate
            gene programs that appear for multiple catgories are only considered
            once).
        """
        self._check_if_trained(warn=True)

        np.random.seed(seed)

        if adata is None:
            adata = self.adata

        active_gps = list(adata.uns[self.active_gp_names_key_])

        # Get selected gps
        if selected_gps is None:
            selected_gps = active_gps
        else:
            if isinstance(selected_gps, str):
                selected_gps = [selected_gps]
            for gp in selected_gps:
                if gp not in active_gps:
                    print(f"GP '{gp}' is not an active gene program. Continuing"
                          " anyways.")

        # Get indeces and weights for selected gps
        selected_gps_idx, selected_gps_weights, chrom_access_gp_weights = self.get_gp_data(
            selected_gps=selected_gps,
            adata=adata)

        # Get gp / latent scores for selected gps
        mu, std = self.get_latent_representation(
            adata=adata,
            counts_key=self.counts_key_,
            adj_key=self.adj_key_,
            condition_key=self.condition_key_,
            only_active_gps=False,
            return_mu_std=True,
            node_batch_size=self.node_batch_size_)
        mu_selected_gps = mu[:, selected_gps_idx]
        std_selected_gps = std[:, selected_gps_idx]

        # Normalize gp scores using the gene expression negative binomial means
        # decoder weights (if ´gp_scores_weight_normaliztion == True´), and, in
        # addition, correct them for zero inflation probabilities if
        # ´self.gene_expr_recon_dist == zinb´. Alternatively (if
        # ´gp_scores_weight_normalization == False´), just use the signs of the
        # summed gene expression negative binomial means decoder weights for
        # normalization. This normalization only causes a difference if a ´zinb´
        # gene expression reconstruction distribution is used as zero inflation
        # probabilities differ for different observations / cells and, as a
        # result also between a category and the comparison categories. The
        # effect of normalizing mu and std by the gene expression negative
        # binomial means decoder weight is cancelled out in the calculation of
        # the log bayes factors
        if gp_scores_weight_normalization:
            norm_factors = selected_gps_weights # dim: (2 x n_genes,
            # n_selected_gps)
            if self.gene_expr_recon_dist_ == "nb":
                mu_norm_factors = norm_factors.mean(0) # sum over genes; dim:
                # (n_selected_gps,)
                std_norm_factors = np.abs(norm_factors.mean(0)) # sum over
                # genes; dim: (n_selected_gps,); proportional increase of std
                # but no negative std
            elif self.gene_expr_recon_dist_ == "zinb":
                # Get zero inflation probabilities
                _, zi_probs = self.get_gene_expr_dist_params(
                    adata=adata,
                    counts_key=self.counts_key_,
                    adj_key=self.adj_key_)
                non_zi_probs = 1 - zi_probs # dim: (n_obs, 2 x n_genes)
                non_zi_probs_rep = np.repeat(non_zi_probs[:, :, np.newaxis],
                                             len(selected_gps),
                                             axis=2) # dim: (n_obs, 2 x n_genes,
                                             # n_selected_gps)
                norm_factors = np.repeat(norm_factors[np.newaxis, :],
                                         mu.shape[0],
                                         axis=0) # dim: (n_obs, 2 x n_genes,
                                         # n_selected_gps)
                norm_factors *= non_zi_probs_rep
        else:
            gp_weights_sum = selected_gps_weights.sum(0) # sum over genes
            gp_signs = np.zeros_like(gp_weights_sum)
            gp_signs[gp_weights_sum>0] = 1. # keep sign of gp score
            gp_signs[gp_weights_sum<0] = -1. # reverse sign of gp score
            norm_factors = gp_signs # dim: (n_selected_gps,)
            mu_norm_factors = norm_factors
            std_norm_factors = 1 # no negative std

        # Retrieve category values for each observation, as well as all existing
        # unique categories
        cat_values = adata.obs[cat_key].replace(np.nan, "NaN")
        cats = cat_values.unique()
        if selected_cats is None:
            selected_cats = cats
        elif isinstance(selected_cats, str):
            selected_cats = [selected_cats]

        # Check specified comparison categories
        if comparison_cats != "rest" and isinstance(comparison_cats, str):
            comparison_cats = [comparison_cats]
        if (comparison_cats != "rest" and not
        set(comparison_cats).issubset(cats)):
            raise ValueError("Comparison categories should be 'rest' (for "
                             "comparison with all other categories) or contain "
                             "existing categories.")

        # Run differential gp tests for all selected categories that are not
        # part of the comparison categories
        results = []
        for cat in selected_cats:
            if cat in comparison_cats:
                continue
            # Filter gp scores and normalization factors for the category under
            # consideration and comparison categories
            cat_mask = cat_values == cat
            if comparison_cats == "rest":
                comparison_cat_mask = ~cat_mask
            else:
                comparison_cat_mask = cat_values.isin(comparison_cats)

            # Aggregate normalization factors
            if norm_factors.ndim == 1 or norm_factors.ndim == 2:
                mu_norm_factors_cat = mu_norm_factors
                mu_norm_factors_comparison_cat =  mu_norm_factors
                std_norm_factors_cat = std_norm_factors
                std_norm_factors_comparison_cat = std_norm_factors
            elif norm_factors.ndim == 3:
                # Compute mean of normalization factors across genes for the
                # category under consideration and the comparison categories
                # respectively
                mu_norm_factors_cat = norm_factors[cat_mask].mean(1)
                std_norm_factors_cat = np.abs(norm_factors[cat_mask].mean(1))
                mu_norm_factors_comparison_cat = (
                    norm_factors[comparison_cat_mask].mean(1)) # dim:
                    # (n_selected_gps,)
                std_norm_factors_comparison_cat = np.abs(
                    norm_factors[comparison_cat_mask].mean(1)) # dim:
                    # (n_selected_gps,)             

            # Normalize gp scores
            mu_selected_gps_cat = (
                mu_selected_gps[cat_mask] * mu_norm_factors_cat)
            std_selected_gps_cat = (
                std_selected_gps[cat_mask] * std_norm_factors_cat)
            mu_selected_gps_comparison_cat = (
                mu_selected_gps[comparison_cat_mask] *
                mu_norm_factors_comparison_cat)
            std_selected_gps_comparison_cat = (
                std_selected_gps[comparison_cat_mask] *
                std_norm_factors_comparison_cat)

            # Generate random samples of category and comparison categories
            # observations with equal size
            cat_idx = np.random.choice(cat_mask.sum(),
                                       n_sample)
            comparison_cat_idx = np.random.choice(comparison_cat_mask.sum(),
                                                  n_sample)
            mu_selected_gps_cat_sample = mu_selected_gps_cat[cat_idx]
            std_selected_gps_cat_sample = std_selected_gps_cat[cat_idx]
            mu_selected_gps_comparison_cat_sample = (
                mu_selected_gps_comparison_cat[comparison_cat_idx])
            std_selected_gps_comparison_cat_sample = (
                std_selected_gps_comparison_cat[comparison_cat_idx])

            # Calculate gene program log Bayes Factors for the category
            to_reduce = (
                - (mu_selected_gps_cat_sample -
                mu_selected_gps_comparison_cat_sample) /
                np.sqrt(2 * (std_selected_gps_cat_sample ** 2 +
                std_selected_gps_comparison_cat_sample ** 2)))
            to_reduce = 0.5 * erfc(to_reduce)
            p_h0 = np.mean(to_reduce, axis=0)
            p_h1 = 1.0 - p_h0
            epsilon = 1e-12
            log_bayes_factor = np.log(p_h0 + epsilon) - np.log(p_h1 + epsilon)
            zeros_mask = (
                (np.abs(mu_selected_gps_cat_sample).sum(0) == 0) | 
                (np.abs(mu_selected_gps_comparison_cat_sample).sum(0) == 0))
            p_h0[zeros_mask] = 0
            p_h1[zeros_mask] = 0
            log_bayes_factor[zeros_mask] = 0

            # Store differential gp test results
            zipped = zip(
                selected_gps,
                p_h0,
                p_h1,
                log_bayes_factor)
            cat_results = [{"category": cat,
                           "gene_program": gp,
                           "p_h0": p_h0,
                           "p_h1": p_h1,
                           "log_bayes_factor": log_bayes_factor}
                          for gp, p_h0, p_h1, log_bayes_factor in zipped]
            for result in cat_results:
                results.append(result)

        # Create test results dataframe and keep only enriched category gene
        # program pairs (log bayes factor above thresh)
        results = pd.DataFrame(results)
        results["abs_log_bayes_factor"] = np.abs(results["log_bayes_factor"])
        results = results[
            results["abs_log_bayes_factor"] > log_bayes_factor_thresh]
        results.sort_values(by="abs_log_bayes_factor",
                            ascending=False,
                            inplace=True)
        results.reset_index(drop=True, inplace=True)
        results.drop("abs_log_bayes_factor", axis=1, inplace=True)
        adata.uns[key_added] = results

        # Normalize gp scores
        if mu_norm_factors.ndim == 2:
            mu_norm_factors = mu_norm_factors.mean(0) # mean over genes,
            # dim: (n_selected_gps,)
        elif norm_factors.ndim == 3:
            mu_norm_factors = norm_factors.mean(1) # mean over genes,
            # dim: (n_obs, n_selected_gps)
        mu_selected_gps *= mu_norm_factors # use broadcasting

        # Retrieve enriched gene programs
        enriched_gps = results["gene_program"].unique().tolist()
        enriched_gps_idx = [selected_gps.index(gp) for gp in enriched_gps]
        
        # Add gene program scores of enriched gene programs to adata
        enriched_gps_gp_scores = pd.DataFrame(
            mu_selected_gps[:, enriched_gps_idx],
            columns=enriched_gps,
            index=adata.obs.index)
        new_cols = [col for col in enriched_gps_gp_scores.columns if col not in
                    adata.obs.columns]
        if new_cols:
            adata.obs = pd.concat([adata.obs,
                                   enriched_gps_gp_scores[new_cols]], axis=1)

        return enriched_gps

    def compute_gp_gene_importances(
            self,
            selected_gp: str,
            adata: Optional[AnnData]=None) -> pd.DataFrame:
        """
        Compute gene importances for the genes of a given gene program. Gene
        importances are determined by the normalized weights of the gene
        expression decoder, corrected for gene expression zero inflation in the
        case of ´self.edge_recon_dist == zinb´.

        Parameters
        ----------
        selected_gp:
            Name of the gene program for which the gene importances should be
            retrieved.
        adata:
            AnnData object to be used. If ´None´, uses the adata object stored
            in the model instance.
     
        Returns
        ----------
        gp_gene_importances_df:
            Pandas DataFrame containing genes, sign-corrected gene weights, gene
            importances and an indicator whether the gene belongs to the
            communication source or target, stored in ´gene_entity´.
        """
        self._check_if_trained(warn=True)
        
        if adata is None:
            adata = self.adata

        # Check if selected gene program is active
        active_gps = adata.uns[self.active_gp_names_key_]
        if selected_gp not in active_gps:
            print(f"GP '{selected_gp}' is not an active gene program. "
                  "Continuing anyways.")

        _, gp_weights, _ = self.get_gp_data(selected_gps=selected_gp,
                                         adata=adata)

        # Correct signs of gp weights to be aligned with (normalized) gp scores
        if gp_weights.sum(0) < 0:
            gp_weights *= -1

        if self.gene_expr_recon_dist_ == "zinb":
            # Correct for zero inflation probabilities
            _, zi_probs = self.get_gene_expr_dist_params(
                adata=adata,
                counts_key=self.counts_key_,
                adj_key=self.adj_key_)
            non_zi_probs = 1 - zi_probs
            gp_weights_zi = gp_weights * non_zi_probs.sum(0) # sum over all obs
            # Normalize gp weights to get gene importances
            gp_gene_importances = np.abs(gp_weights_zi / np.abs(gp_weights_zi).sum(0))
        elif self.gene_expr_recon_dist_ == "nb":
            # Normalize gp weights to get gene importances
            gp_gene_importances = np.abs(gp_weights / np.abs(gp_weights).sum(0))

        # Create result dataframe
        gp_gene_importances_df = pd.DataFrame()
        gp_gene_importances_df["gene"] = [gene for gene in
                                          adata.var_names.tolist()] * 2
        gp_gene_importances_df["gene_entity"] = (["target"] *
                                                 len(adata.var_names) +
                                                 ["source"] *
                                                 len(adata.var_names))
        gp_gene_importances_df["gene_weight_sign_corrected"] = gp_weights
        gp_gene_importances_df["gene_importance"] = gp_gene_importances
        gp_gene_importances_df = (gp_gene_importances_df
            [gp_gene_importances_df["gene_importance"] != 0])
        gp_gene_importances_df.sort_values(by="gene_importance",
                                           ascending=False,
                                           inplace=True)
        gp_gene_importances_df.reset_index(drop=True, inplace=True)
        return gp_gene_importances_df
    
    def compute_gp_peak_importances(
            self,
            selected_gp: str,
            adata: Optional[AnnData]=None,
            adata_atac: Optional[AnnData]=None) -> pd.DataFrame:
        """
        Compute peak importances for the peaks of a given gene program. Peak
        importances are determined by the normalized weights of the chromatin
        accessibility decoder.

        Parameters
        ----------
        selected_gp:
            Name of the gene program for which the peak importances should be
            retrieved.
        adata:
            AnnData object to be used. If ´None´, uses the adata object stored
            in the model instance.
        adata_atac:
            ATAC AnnData object to be used. If ´None´, uses the adata_atac
            object stored in the model instance.
     
        Returns
        ----------
        gp_peak_importances_df:
            Pandas DataFrame containing peaks, sign-corrected peak weights, peak
            importances and an indicator whether the peak belongs to the
            communication source or target, stored in ´peak_entity´.
        """
        self._check_if_trained(warn=True)

        if not "chrom_access" in self.modalities_:
            raise ValueError("The model training needs to include ATAC data, "
                             "otherwise peak importances cannot be retrieved.")
        
        if adata is None:
            adata = self.adata

        if adata_atac is None:
            adata_atac = self.adata_atac

        # Check if selected gene program is active
        active_gps = adata.uns[self.active_gp_names_key_]
        if selected_gp not in active_gps:
            print(f"GP '{selected_gp}' is not an active gene program. "
                  "Continuing anyways.")

        _, gp_gene_expr_weights, gp_chrom_access_weights = self.get_gp_data(
            selected_gps=selected_gp,
            adata=adata)

        # Correct signs of GP chrom access weights to be aligned with
        # (normalized) GP scores. Note that GP scores are normalized based on
        # gene expr weights
        if gp_gene_expr_weights.sum(0) < 0:
            gp_chrom_access_weights *= -1

        # Normalize GP chrom access weights to get peak importances
        gp_peak_importances = np.abs(
            gp_chrom_access_weights / np.abs(gp_chrom_access_weights).sum(0))

        # Create result dataframe
        gp_peak_importances_df = pd.DataFrame()
        gp_peak_importances_df["peak"] = [peak for peak in
                                          adata_atac.var_names.tolist()] * 2
        gp_peak_importances_df["peak_entity"] = (["target"] *
                                                 len(adata_atac.var_names) +
                                                 ["source"] *
                                                 len(adata_atac.var_names))
        gp_peak_importances_df["peak_weight_sign_corrected"] = (
            gp_chrom_access_weights)
        gp_peak_importances_df["peak_importance"] = gp_peak_importances
        gp_peak_importances_df = (gp_peak_importances_df
            [gp_peak_importances_df["peak_importance"] != 0])
        gp_peak_importances_df.sort_values(by="peak_importance",
                                           ascending=False,
                                           inplace=True)
        gp_peak_importances_df.reset_index(drop=True, inplace=True)
        return gp_peak_importances_df

    def compute_latent_graph_connectivities(
            self,
            n_neighbors: int=15,
            mode: Literal["knn", "umap"]="knn",
            seed: int=42,
            adata: Optional[AnnData]=None):
        """
        Compute latent graph connectivities.

        Parameters
        ----------
        n_neighbors:
            Number of neighbors for graph connectivities computation.
        mode:
            Mode to be used for graph connectivities computation.
        seed:
            Random seed for reproducible computation.
        adata:
            AnnData object to be used. If ´None´, uses the adata object stored 
            in the model instance.
        """
        self._check_if_trained(warn=True)

        if adata is None:
            adata = self.adata

        # Validate that latent representation exists
        if self.latent_key_ not in adata.obsm:
            raise ValueError(f"Key '{self.latent_key_}' not found in "
                              "'adata.obsm'. Please make sure to first train "
                              "the model and store the latent representation in"
                              " 'adata.obsm'.")

        # Compute latent connectivities
        sc.pp.neighbors(adata=adata,
                        use_rep=self.latent_key_,
                        n_neighbors=n_neighbors,
                        random_state=seed,
                        key_added="latent")

    def get_gp_data(self,
                    selected_gps: Optional[Union[str, list]]=None,
                    adata: Optional[AnnData]=None
                    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get the index of selected gene programs as well as their gene weights of
        the gene expression negative binomial means decoder.

        Parameters:
        ----------
        selected_gps:
            Names of the selected gene programs for which data should be
            retrieved.
        adata:
            AnnData object to be used. If ´None´, uses the adata object stored
            in the model instance.

        Returns:
        ----------
        selected_gps_idx:
            Index of the selected gene programs (dim: n_selected_gps,)
        selected_gp_weights:
            Gene expression decoder gene weights of the selected gene programs
            (dim: (n_genes, n_gps) if ´self.node_label_method == self´ or
            (2 x n_genes, n_gps) otherwise).
        """
        self._check_if_trained(warn=True)
        
        if adata is None:
            adata = self.adata

        # Get selected gps and their index
        all_gps = list(adata.uns[self.gp_names_key_])
        if selected_gps is None:
            selected_gps = all_gps
        elif isinstance(selected_gps, str):
            selected_gps = [selected_gps]
        selected_gps_idx = np.array([all_gps.index(gp) for gp in selected_gps])

        # Get weights of selected gps
        all_gps_gene_expr_weights = self.model.get_gp_weights()[0]
        selected_gps_gene_expr_weights = (
            all_gps_gene_expr_weights[:, selected_gps_idx]
            .cpu().detach().numpy())
        
        if "chrom_access" in self.modalities_:
            all_gps_chrom_access_weights = self.model.get_gp_weights()[1]
            selected_gps_chrom_access_weights = (
                all_gps_chrom_access_weights[:, selected_gps_idx]
                .cpu().detach().numpy())
        else:
            selected_gps_chrom_access_weights = None

        return (selected_gps_idx,
                selected_gps_gene_expr_weights,
                selected_gps_chrom_access_weights)

    def get_cond_embeddings(self) -> np.ndarray:
        """
        Get the conditional embeddings.

        Returns:
        ----------
        cond_embed:
            Conditional embeddings.
        """
        self._check_if_trained(warn=True)
        
        cond_embed = self.model.cond_embedder.weight.cpu().detach().numpy()
        return cond_embed

    def get_active_gps(self) -> np.ndarray:
        """
        Get active gene programs based on the gene expression decoder gene
        weights of gene programs. Active gene programs are gene programs
        whose absolute gene weights aggregated over all genes are greater than
        ´self.active_gp_thresh_ratio_´ times the absolute gene weights
        aggregation of the gene program with the maximum value across all gene 
        programs.

        Parameters
        ----------
        adata:
            AnnData object to get the active gene programs for. If ´None´, uses
            the adata object stored in the model instance.

        Returns
        ----------
        active_gps:
            Gene program names of active gene programs (dim: n_active_gps,)
        """
        self._check_if_trained(warn=True)

        active_gp_mask = self.model.get_active_gp_mask()
        active_gp_mask = active_gp_mask.detach().cpu().numpy()
        active_gps = self.adata.uns[self.gp_names_key_][active_gp_mask]
        return active_gps

    def get_latent_representation(
            self, 
            adata: Optional[AnnData]=None,
            adata_atac: Optional[AnnData]=None,
            counts_key: Optional[str]="counts",
            adj_key: str="spatial_connectivities",
            condition_key: Optional[str]=None,
            only_active_gps: bool=True,
            return_mu_std: bool=False,
            node_batch_size: int=64,
            ) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
        """
        Get the latent / gene program representation from a trained model.

        Parameters
        ----------
        adata:
            AnnData object to get the latent representation for. If ´None´, uses
            the adata object stored in the model instance.
        counts_key:
            Key under which the counts are stored in ´adata.layer´. If ´None´,
            uses ´adata.X´ as counts. 
        adj_key:
            Key under which the sparse adjacency matrix is stored in 
            ´adata.obsp´.
        condition_key:
            Key under which the conditions are stored in ´adata.obs´.              
            only_active_gps:
            If ´True´, return only the latent representation of active gps.            
        return_mu_std:
            If `True`, return ´mu´ and ´std´ instead of latent features ´z´.

        Returns
        ----------
        z:
            Latent space features (dim: n_obs x n_active_gps or n_obs x n_gps).
        mu:
            Expected values of the latent posterior (dim: n_obs x n_active_gps 
            or n_obs x n_gps).
        std:
            Standard deviations of the latent posterior (dim: n_obs x 
            n_active_gps or n_obs x n_gps).
        """
        self._check_if_trained(warn=False)
        
        device = next(self.model.parameters()).device

        if adata is None:
            adata = self.adata
        if (adata_atac is None) & hasattr(self, "adata_atac"):
            adata_atac = self.adata_atac

        # Create single dataloader containing entire dataset
        data_dict = prepare_data(
            adata=adata,
            condition_label_encoder=self.model.condition_label_encoder_,
            adata_atac=adata_atac,
            counts_key=counts_key,
            adj_key=adj_key,
            condition_key=condition_key,
            edge_val_ratio=0.,
            edge_test_ratio=0.,
            node_val_ratio=0.,
            node_test_ratio=0.)
        node_masked_data = data_dict["node_masked_data"]
        loader_dict = initialize_dataloaders(
            node_masked_data=node_masked_data,
            edge_train_data=None,
            edge_val_data=None,
            edge_batch_size=None,
            node_batch_size=node_batch_size,
            shuffle=False)
        node_loader = loader_dict["node_train_loader"]

        # Get number of gene programs
        if only_active_gps:
            n_gps = self.get_active_gps().shape[0]
        else:
            n_gps = (self.n_nonaddon_gps_ + self.n_addon_gps_ )

        # Initialize latent vectors
        if return_mu_std:
            mu = np.empty(shape=(adata.shape[0], n_gps))
            std = np.empty(shape=(adata.shape[0], n_gps))
        else:
            z = np.empty(shape=(adata.shape[0], n_gps))

        # Get latent representation for each batch of the dataloader and put it
        # into latent vectors
        for i, node_batch in enumerate(node_loader):
            n_obs_before_batch = i * node_batch_size
            n_obs_after_batch = n_obs_before_batch + node_batch.batch_size
            node_batch = node_batch.to(device)
            if return_mu_std:
                mu_batch, std_batch = self.model.get_latent_representation(
                    node_batch=node_batch,
                    only_active_gps=only_active_gps,
                    return_mu_std=True)
                mu[n_obs_before_batch:n_obs_after_batch, :] = (
                    mu_batch.detach().cpu().numpy())
                std[n_obs_before_batch:n_obs_after_batch, :] = (
                    std_batch.detach().cpu().numpy())
            else:
                z_batch = self.model.get_latent_representation(
                    node_batch=node_batch,
                    only_active_gps=only_active_gps,
                    return_mu_std=False)
                z[n_obs_before_batch:n_obs_after_batch, :] = (
                    z_batch.detach().cpu().numpy())
        if return_mu_std:
            return mu, std
        else:
            return z
    
    @torch.no_grad()
    def get_recon_edge_probs(self,      
                             node_batch_size: int=2048,
                             device: Optional[str]=None,
                             edge_thresh: Optional[float]=None,
                             n_neighbors: Optional[int]=None,
                             return_edge_probs: bool=False
                             ) -> Union[sp.csr_matrix, torch.Tensor]:
        """
        Get the reconstructed adjacency matrix (or edge probability matrix if 
        ´return_edge_probs == True´ from a trained NicheCompass model.

        Parameters
        ----------
        node_batch_size:
            Batch size for batched decoder forward pass to alleviate memory
            consumption. Only relevant if ´return_edge_probs == False´.
        device:
            Device where the computation will be executed.
        edge_thresh:
            Probability threshold above or equal to which edge probabilities
            lead to a reconstructed edge. If ´None´, ´n_neighbors´ will be used
            to compute an independent edge threshold for each observation.
        n_neighbors:
            Number of neighbors used to compute an independent edge threshold
            for each observation (before the adjacency matrix is made
            symmetric).Only applies if ´edge_thresh is None´. In some occassions
            when multiple edges have the same probability, the number of
            reconstructed edges can slightly deviate from ´n_neighbors´. If
            ´None´, the number of neighbors in the original (symmetric) spatial
            graph stored in ´adata.obsp[self.adj_key_]´ are used to compute an
            independent edge threshold for each observation (in this case the
            adjacency matrix is not made symmetric). 
        return_edge_probs:
            If ´True´, return a matrix of edge probabilities instead of the
            reconstructed adjacency matrix. This will require a lot of memory
            as a dense tensor will be returned instead of a sparse matrix.

        Returns
        ----------
        adj_recon:
            Sparse scipy matrix containing reconstructed edges (dim: n_nodes x
            n_nodes).
        adj_recon_probs:
            Tensor containing edge probabilities (dim: n_nodes x n_nodes).
        """
        self._check_if_trained(warn=False)
        model_device = next(self.model.parameters()).device
        if device is None:
            # Get device from model
            device = model_device
        else:
            self.model.to(device)

        if edge_thresh is None:
            compute_edge_thresh = True

        # Get conditional embeddings for each observation
        if (len(self.conditions_) > 0) & \
        ("graph_decoder" in self.cond_embed_injection_):
            if self.cond_embed_key_ not in self.adata.uns:
                raise ValueError("Please first store the conditional embeddings"
                                f" in adata.uns['{self.cond_embed_key_}']. They"
                                " can be retrieved via "
                                "'model.get_cond_embeddings()'.")
            cond_labels = self.adata.obs[self.condition_key_]
            cond_label_encodings = cond_labels.map(
                self.model.condition_label_encoder_).values
            cond_embed = torch.tensor(
                self.adata.uns[self.cond_embed_key_][cond_label_encodings],
                device=device)
        else:
            cond_embed = None
        
        # Get the latent representation for each observation
        if self.latent_key_ not in self.adata.obsm:
            raise ValueError("Please first store the latent representations in "
                             f"adata.obsm['{self.latent_key_}']. They can be "
                             "retrieved via "
                             "'model.get_latent_representation()'.")
        z = torch.tensor(self.adata.obsm[self.latent_key_], device=device)

        # Add 0s for inactive gps back to stored latent representation which
        # only contains active gps (model expects all gps with inactive ones
        # having 0 values)
        active_gp_mask = self.model.get_active_gp_mask()
        z_with_inactive = torch.zeros((z.shape[0], active_gp_mask.shape[0]),
                                      dtype=torch.float64, device=device)
        active_gp_idx = (active_gp_mask == 1).nonzero().t()
        active_gp_idx = active_gp_idx.repeat(z_with_inactive.shape[0], 1)
        z_with_inactive = z_with_inactive.scatter(1, active_gp_idx, z)

        if not return_edge_probs:
            # Initialize global reconstructed adjacency matrix
            adj_recon = sp.lil_matrix((len(self.adata), len(self.adata)))

            for i in range(0, len(self.adata), node_batch_size):
                # Get edge probabilities for current batch
                adj_recon_logits = self.model.graph_decoder(
                    z=z_with_inactive,
                    cond_embed=cond_embed,
                    reduced_obs_start_idx=i,
                    reduced_obs_end_idx=i+node_batch_size)
                adj_recon_probs_batch = torch.sigmoid(adj_recon_logits)

                if compute_edge_thresh:
                    if n_neighbors is None:
                        # Get neighbors from spatial (input) adjacency matrix
                        n_neighs_adj = np.array(
                            self.adata.obsp[self.adj_key_][i: i+node_batch_size]
                            .sum(axis=1).astype(int)).flatten()
                    else:
                        n_neighs_adj = np.ones(
                            [adj_recon_probs_batch.shape[0]],
                            dtype=int) * n_neighbors
                    adj_recon_probs_batch_sorted = adj_recon_probs_batch.sort(
                        descending=True)[0]
                    edge_thresh = adj_recon_probs_batch_sorted[
                        np.arange(adj_recon_probs_batch_sorted.shape[0]),
                        n_neighs_adj-1]
                    edge_thresh = edge_thresh.view(-1, 1).expand_as(
                        adj_recon_probs_batch)

                # Convert edge probabilities to edges
                adj_recon_batch = (adj_recon_probs_batch >= edge_thresh).long()
                adj_recon_batch = adj_recon_batch.cpu().numpy()
                adj_recon[i:i+node_batch_size, :] = adj_recon_batch
        else:
            adj_recon_logits = self.model.graph_decoder(
                z=z_with_inactive,
                cond_embed=cond_embed)
            adj_recon_probs = torch.sigmoid(adj_recon_logits)

        if device is not None:
            # Move model back to original device
            self.model.to(model_device)

        if not return_edge_probs:
            adj_recon = adj_recon.tocsr(copy=False)
            if n_neighbors is not None:
                # Make adjacency matrix symmetric
                adj_recon = adj_recon.maximum(adj_recon.T)
            return adj_recon
        else:
            return adj_recon_probs

    @torch.no_grad()
    def get_gene_expr_agg_att_weights(
            self,      
            node_batch_size: int=64) -> sp.csr_matrix:
        """
        Get the mean attention weights (over all heads) of the gene expression
        node label aggregator. The attention weights indicate how much
        importance each node / observation has attributed to its neighboring
        nodes / observations for the gene expression reconstruction task.

        Parameters
        ----------
        node_batch_size:
            Batch size that is used by the dataloader.

        Returns
        ----------
        agg_alpha:
            A sparse scipy matrix containing the mean attention weights over all
            heads of the gene expression node label aggregator (dim: n_obs x
            n_obs). Row-wise sums will be 1 for each observation. The matrix is
            not symmetric.
        """
        self._check_if_trained(warn=False)
        device = next(self.model.parameters()).device

        if self.node_label_method_ != "one-hop-attention":
            raise ValueError("The node label aggregator attention weights can "
                             " only be retrieved if 'one-hop-attention' has "
                             "been used as node label method.")

        # Initialize global attention weights matrix
        agg_alpha = sp.lil_matrix((len(self.adata), len(self.adata)))

        # Create single dataloader containing entire dataset
        data_dict = prepare_data(
            adata=self.adata,
            condition_label_encoder=self.model.condition_label_encoder_,
            counts_key=self.counts_key_,
            adj_key=self.adj_key_,
            condition_key=self.condition_key_,
            edge_val_ratio=0.,
            edge_test_ratio=0.,
            node_val_ratio=0.,
            node_test_ratio=0.)
        node_masked_data = data_dict["node_masked_data"]
        loader_dict = initialize_dataloaders(
            node_masked_data=node_masked_data,
            edge_train_data=None,
            edge_val_data=None,
            edge_batch_size=None,
            node_batch_size=node_batch_size,
            shuffle=False)
        node_loader = loader_dict["node_train_loader"]

        # Get attention weights for each node batch of the dataloader and put
        # them into the global attention weights matrix
        for i, node_batch in enumerate(node_loader):
            node_batch = node_batch.to(device)
            n_obs_before_batch = i * node_batch_size
            n_obs_after_batch = n_obs_before_batch + node_batch.batch_size

            _, alpha = (self.model.node_label_aggregator(
                x=node_batch.x,
                edge_index=node_batch.edge_index,
                return_attention_weights=True))

            # Get edge index and attention weights of current node batch only
            # (exclude sampled neighbors)
            alpha_edge_index = node_batch.edge_attr[
                (node_batch.edge_attr[:, 1] >= n_obs_before_batch) &
                (node_batch.edge_attr[:, 1] < n_obs_after_batch)]
            alpha = alpha[:alpha_edge_index.shape[0]]

            # Compute mean over attention heads
            mean_alpha = alpha.mean(dim=-1)

            # Insert attention weights from current node batch in global
            # attention weights matrix
            alpha_edge_index = alpha_edge_index.cpu().numpy()
            mean_alpha = mean_alpha.cpu().numpy()
            agg_alpha[alpha_edge_index[:, 1],
                      alpha_edge_index[:, 0]] = mean_alpha
        agg_alpha = agg_alpha.tocsr(copy=False)
        return agg_alpha
    

    def get_gene_expr_dist_params(
            self, 
            adata: Optional[AnnData]=None,
            counts_key: str="counts",
            adj_key: str="spatial_connectivities",
            ) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
        """
        Get the gene expression distribution parameters from a trained model. 
        This is either (´nb_means´, ´zi_probs´) if a zero-inflated negative 
        binomial is used to model gene expression or ´nb_means´ if a negative 
        binomial is used to model gene expression.

        Parameters
        ----------
        adata:
            AnnData object to get the gene expression distribution parameters
            for. If ´None´, uses the adata object stored in the model instance.
        counts_key:
            Key under which the counts are stored in ´adata.layer´. If ´None´,
            uses ´adata.X´ as counts.  
        adj_key:
            Key under which the sparse adjacency matrix is stored in 
            ´adata.obsp´.       

        Returns
        ----------
        nb_means:
            Expected values of the negative binomial distribution (dim: n_obs x
            n_genes).
        zi_probs:
            Zero-inflation probabilities of the zero-inflated negative binomial
            distribution (dim: n_obs x n_genes).
        """
        self._check_if_trained(warn=False)

        device = next(self.model.parameters()).device
        
        if adata is None:
            adata = self.adata

        dataset = SpatialAnnTorchDataset(adata=adata,
                                         counts_key=counts_key,
                                         adj_key=adj_key)
        x = dataset.x.to(device)
        edge_index = dataset.edge_index.to(device)
        log_library_size = torch.log(x.sum(1)).unsqueeze(1)

        mu, _ = self.model.get_latent_representation(
            x=x,
            edge_index=edge_index,
            only_active_gps=False,
            return_mu_std=True)

        if self.gene_expr_recon_dist_ == "nb":
            nb_means = self.model.get_gene_expr_dist_params(
                z=mu,
                log_library_size=log_library_size)
            nb_means = nb_means.detach().cpu().numpy()
            return nb_means
        if self.gene_expr_recon_dist_ == "zinb":
            nb_means, zi_prob_logits = self.model.get_gene_expr_dist_params(
                z=mu,
                log_library_size=log_library_size)
            zi_probs = torch.sigmoid(zi_prob_logits)
            nb_means = nb_means.detach().cpu().numpy()
            zi_probs = zi_probs.detach().cpu().numpy()
            return nb_means, zi_probs

    def get_gp_summary(self) -> pd.DataFrame:
        """
        Returns
        ----------
        gp_summary_df:
            DataFrame with gene program summary information.

        TO DO: extend to addon gps.
        """
        # Get source and target (sign corrected) gene weights
        _, gp_weights, chrom_access_gp_weights = self.get_gp_data()
        gp_weights_sum = gp_weights.sum(0) # sum over genes
        gp_weights_signs = np.zeros_like(gp_weights_sum)
        gp_weights_signs[gp_weights_sum>0] = 1. # keep sign of gp score
        gp_weights_signs[gp_weights_sum<0] = -1. # reverse sign of gp score
        gp_weights *= gp_weights_signs

        if self.gene_expr_recon_dist_ == "zinb":
            # Correct for zero inflation probabilities
            _, zi_probs = self.get_gene_expr_dist_params(
                adata=self.adata,
                counts_key=self.counts_key_,
                adj_key=self.adj_key_)
            non_zi_probs = 1 - zi_probs
            gp_weights_zi = gp_weights * non_zi_probs.sum(0) # sum over all obs
            # Normalize gp weights to get gene importances
            gp_gene_importances = np.abs(gp_weights_zi / np.abs(gp_weights_zi).sum(0))
        elif self.gene_expr_recon_dist_ == "nb":
            # Normalize gp weights to get gene importances
            gp_gene_importances = np.abs(gp_weights / np.abs(gp_weights).sum(0))            

        gp_weights = np.transpose(gp_weights)
        gp_gene_importances = np.transpose(gp_gene_importances)
        gp_source_genes_weights_all_arr = gp_weights[:, int(gp_weights.shape[1]/2):]
        gp_target_genes_weights_all_arr = gp_weights[:, :int(gp_weights.shape[1]/2)]
        gp_source_gene_importances_all_arr = gp_gene_importances[:, int(gp_weights.shape[1]/2):]
        gp_target_gene_importances_all_arr = gp_gene_importances[:, :int(gp_weights.shape[1]/2)]

        # Get source and target genes
        gp_source_genes_mask = np.transpose(
            self.adata.varm[self.gp_sources_mask_key_] != 0)
        gp_target_genes_mask = np.transpose(
            self.adata.varm[self.gp_targets_mask_key_] != 0)
        
        # Add entries to gp mask for addon gps
        if self.n_addon_gps_ > 0:
            addon_gp_source_genes_mask = np.ones((self.n_addon_gps_,
                                                  self.adata.n_vars), dtype=bool)
            addon_gp_target_genes_mask = np.ones((self.n_addon_gps_,
                                                  self.adata.n_vars), dtype=bool)
            gp_source_genes_mask = np.concatenate(
                (gp_source_genes_mask, addon_gp_source_genes_mask), axis=0)
            gp_target_genes_mask = np.concatenate(
                (gp_target_genes_mask, addon_gp_target_genes_mask), axis=0)

        # Get active gp mask
        gp_active_status = np.array(self.model.get_active_gp_mask()).tolist()

        active_gps = list(self.get_active_gps())
        all_gps = list(self.adata.uns[self.gp_names_key_])

        # Collect info for each gp in lists of lists
        gp_names = []
        active_gp_idx = [] # Index among active gene programs
        all_gp_idx = [] # Index among all gene programs
        n_source_genes = []
        n_non_zero_source_genes = []
        n_target_genes = []
        n_non_zero_target_genes = []
        gp_source_genes = []
        gp_target_genes = []
        gp_source_genes_weights = []
        gp_target_genes_weights = []
        gp_source_genes_importances = []
        gp_target_genes_importances = []
        for (gp_name,
             gp_source_genes_idx,
             gp_target_genes_idx,
             gp_source_genes_weights_arr,
             gp_target_genes_weights_arr,
             gp_source_genes_importances_arr,
             gp_target_genes_importances_arr) in zip(
                self.adata.uns[self.gp_names_key_],
                gp_source_genes_mask,
                gp_target_genes_mask,
                gp_source_genes_weights_all_arr,
                gp_target_genes_weights_all_arr,
                gp_source_gene_importances_all_arr,
                gp_target_gene_importances_all_arr):
            gp_names.append(gp_name)
            active_gp_idx.append(active_gps.index(gp_name)
                                 if gp_name in active_gps else np.nan)
            all_gp_idx.append(all_gps.index(gp_name))

            # Sort source genes according to absolute weights
            sorted_source_genes_weights = []
            sorted_source_genes_importances = []
            sorted_source_genes = []
            for _, weights, importances, genes in sorted(zip(
                np.abs(np.around(gp_source_genes_weights_arr[gp_source_genes_idx],
                                 decimals=4)),
                np.around(gp_source_genes_weights_arr[gp_source_genes_idx],
                          decimals=4),
                np.around(gp_source_genes_importances_arr[gp_source_genes_idx],
                          decimals=4),        
                self.adata.var_names[gp_source_genes_idx].tolist()),reverse=True):
                    sorted_source_genes.append(genes)
                    sorted_source_genes_weights.append(weights)
                    sorted_source_genes_importances.append(importances)
            
            # Sort target genes according to absolute weights
            sorted_target_genes_weights = []
            sorted_target_genes_importances = []
            sorted_target_genes = []
            for _, weights, importances, genes in sorted(zip(
                np.abs(np.around(gp_target_genes_weights_arr[gp_target_genes_idx],
                                 decimals=4)),
                np.around(gp_target_genes_weights_arr[gp_target_genes_idx],
                          decimals=4),                 
                np.around(gp_target_genes_importances_arr[gp_target_genes_idx],
                          decimals=4),
                self.adata.var_names[gp_target_genes_idx].tolist()), reverse=True):
                    sorted_target_genes.append(genes)
                    sorted_target_genes_weights.append(weights)
                    sorted_target_genes_importances.append(importances)                 
                
            n_source_genes.append(len(sorted_source_genes))
            n_non_zero_source_genes.append(len(np.array(
                sorted_source_genes_weights).nonzero()[0]))
            n_target_genes.append(len(sorted_target_genes))
            n_non_zero_target_genes.append(len(np.array(
                sorted_target_genes_weights).nonzero()[0]))
            gp_source_genes.append(sorted_source_genes)
            gp_target_genes.append(sorted_target_genes)
            gp_source_genes_weights.append(sorted_source_genes_weights)
            gp_target_genes_weights.append(sorted_target_genes_weights)
            gp_source_genes_importances.append(sorted_source_genes_importances)
            gp_target_genes_importances.append(sorted_target_genes_importances)
   
        gp_summary_df = pd.DataFrame(
            {"gp_name": gp_names,
             "all_gp_idx": all_gp_idx,
             "gp_active": gp_active_status,
             "active_gp_idx": active_gp_idx,
             "n_source_genes": n_source_genes,
             "n_non_zero_source_genes": n_non_zero_source_genes,
             "n_target_genes": n_target_genes,
             "n_non_zero_target_genes": n_non_zero_target_genes,
             "gp_source_genes": gp_source_genes,
             "gp_target_genes": gp_target_genes,
             "gp_source_genes_weights_sign_corrected": gp_source_genes_weights,
             "gp_target_genes_weights_sign_corrected": gp_target_genes_weights,
             "gp_source_genes_importances": gp_source_genes_importances,
             "gp_target_genes_importances": gp_target_genes_importances})
        
        gp_summary_df["active_gp_idx"] = (
            gp_summary_df["active_gp_idx"].astype("Int64"))
        
        if "chrom_access" in self.modalities_:
            gp_peak_importances = np.abs(
                chrom_access_gp_weights / np.abs(chrom_access_gp_weights).sum(0))
            chrom_access_gp_weights = np.transpose(chrom_access_gp_weights)
            gp_peak_importances = np.transpose(gp_peak_importances)
            gp_source_peaks_weights_all_arr = chrom_access_gp_weights[
                :, int(chrom_access_gp_weights.shape[1]/2):]
            gp_target_peaks_weights_all_arr = chrom_access_gp_weights[
                :, :int(chrom_access_gp_weights.shape[1]/2)]
            gp_source_peak_importances_all_arr = gp_peak_importances[
                :, int(chrom_access_gp_weights.shape[1]/2):]
            gp_target_peak_importances_all_arr = gp_peak_importances[
                :, :int(chrom_access_gp_weights.shape[1]/2)]

            # Get source and target peaks
            gp_source_peaks_mask = np.transpose(
                self.adata_atac.varm[self.ca_sources_mask_key_] != 0).toarray()
            gp_target_peaks_mask = np.transpose(
                self.adata_atac.varm[self.ca_targets_mask_key_] != 0).toarray()
        
            # Add entries to gp mask for addon gps
            if self.n_addon_gps_ > 0:
                addon_gp_source_peaks_mask = np.ones(
                    (self.n_addon_gps_,
                     self.adata_atac.n_vars), dtype=bool)
                addon_gp_target_peaks_mask = np.ones(
                    (self.n_addon_gps_,
                     self.adata_atac.n_vars), dtype=bool)
                gp_source_peaks_mask = np.concatenate(
                    (gp_source_peaks_mask, addon_gp_source_peaks_mask), axis=0)
                gp_target_peaks_mask = np.concatenate(
                    (gp_target_peaks_mask, addon_gp_target_peaks_mask), axis=0)

            # Collect info for each gp in lists of lists
            n_source_peaks = []
            n_non_zero_source_peaks = []
            n_target_peaks = []
            n_non_zero_target_peaks = []
            gp_source_peaks = []
            gp_target_peaks = []
            gp_source_peaks_weights = []
            gp_target_peaks_weights = []
            gp_source_peaks_importances = []
            gp_target_peaks_importances = []
            for (gp_source_peaks_idx,
                 gp_target_peaks_idx,
                 gp_source_peaks_weights_arr,
                 gp_target_peaks_weights_arr,
                 gp_source_peaks_importances_arr,
                 gp_target_peaks_importances_arr) in zip(
                    gp_source_peaks_mask,
                    gp_target_peaks_mask,
                    gp_source_peaks_weights_all_arr,
                    gp_target_peaks_weights_all_arr,
                    gp_source_peak_importances_all_arr,
                    gp_target_peak_importances_all_arr):
                # Sort source peaks according to absolute weights
                sorted_source_peaks_weights = []
                sorted_source_peaks_importances = []
                sorted_source_peaks = []
                for _, weights, importances, peaks in sorted(zip(
                    np.abs(np.around(gp_source_peaks_weights_arr[gp_source_peaks_idx],
                                    decimals=4)),
                    np.around(gp_source_peaks_weights_arr[gp_source_peaks_idx],
                            decimals=4),
                    np.around(gp_source_peaks_importances_arr[gp_source_peaks_idx],
                            decimals=4),        
                    self.adata_atac.var_names[gp_source_peaks_idx].tolist()),reverse=True):
                        sorted_source_peaks.append(peaks)
                        sorted_source_peaks_weights.append(weights)
                        sorted_source_peaks_importances.append(importances)
                
                # Sort target peaks according to absolute weights
                sorted_target_peaks_weights = []
                sorted_target_peaks_importances = []
                sorted_target_peaks = []
                for _, weights, importances, peaks in sorted(zip(
                    np.abs(np.around(gp_target_peaks_weights_arr[gp_target_peaks_idx],
                                    decimals=4)),
                    np.around(gp_target_peaks_weights_arr[gp_target_peaks_idx],
                            decimals=4),                 
                    np.around(gp_target_peaks_importances_arr[gp_target_peaks_idx],
                            decimals=4),
                    self.adata_atac.var_names[gp_target_peaks_idx].tolist()), reverse=True):
                        sorted_target_peaks.append(peaks)
                        sorted_target_peaks_weights.append(weights)
                        sorted_target_peaks_importances.append(importances)                 
                    
                n_source_peaks.append(len(sorted_source_peaks))
                n_non_zero_source_peaks.append(len(np.array(
                    sorted_source_peaks_weights).nonzero()[0]))
                n_target_peaks.append(len(sorted_target_peaks))
                n_non_zero_target_peaks.append(len(np.array(
                    sorted_target_peaks_weights).nonzero()[0]))
                gp_source_peaks.append(sorted_source_peaks)
                gp_target_peaks.append(sorted_target_peaks)
                gp_source_peaks_weights.append(sorted_source_peaks_weights)
                gp_target_peaks_weights.append(sorted_target_peaks_weights)
                gp_source_peaks_importances.append(sorted_source_peaks_importances)
                gp_target_peaks_importances.append(sorted_target_peaks_importances)

            gp_summary_df["n_source_peaks"] = n_source_peaks
            gp_summary_df["n_target_peaks"] = n_target_peaks
            gp_summary_df["gp_source_peaks"] = gp_source_peaks
            gp_summary_df["gp_target_peaks"] = gp_target_peaks
            gp_summary_df["gp_source_peaks_weights_sign_corrected"] = gp_source_peaks_weights
            gp_summary_df["gp_target_peaks_weights_sign_corrected"] = gp_target_peaks_weights
            gp_summary_df["gp_source_peaks_importances"] = gp_source_peaks_importances
            gp_summary_df["gp_target_peaks_importances"] = gp_target_peaks_importances
        
        return gp_summary_df