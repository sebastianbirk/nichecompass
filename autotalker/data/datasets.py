"""
This module contains the SpatialAnnTorchDataset class to provide a standardized
dataset format for the training of an Autotalker model.
"""

from typing import Optional

import scipy.sparse as sp
import torch
from anndata import AnnData

from .utils import encode_labels, sparse_mx_to_sparse_tensor


class SpatialAnnTorchDataset():
    """
    Spatially annotated torch dataset class to extract node features, node 
    labels, adjacency matrix and edge indices in a standardized format from an 
    AnnData object.

    Parameters
    ----------
    adata:
        AnnData object with raw counts stored in ´adata.layers[counts_key]´, and
        sparse adjacency matrix stored in ´adata.obsp[adj_key]´.
    counts_key:
        Key under which the raw counts are stored in ´adata.layer´.
    adj_key:
        Key under which the sparse adjacency matrix is stored in ´adata.obsp´.
    condition_key:
        Key under which the condition for the conditional embedding is stored in
        ´adata.obs´.
    """
    def __init__(self,
                 adata: AnnData,
                 counts_key: str="counts",
                 adj_key: str="spatial_connectivities",
                 condition_key: Optional[str]=None):
        # Store features in dense format
        if sp.issparse(adata.layers[counts_key]): 
            self.x = torch.tensor(adata.layers[counts_key].toarray())
        else:
            self.x = torch.tensor(adata.layers[counts_key])

        # Store adjacency matrix in torch_sparse SparseTensor format
        if sp.issparse(adata.obsp[adj_key]):
            self.adj = sparse_mx_to_sparse_tensor(adata.obsp[adj_key])
        else:
            self.adj = sparse_mx_to_sparse_tensor(
                sp.csr_matrix(adata.obsp[adj_key]))

        # Validate adjacency matrix symmetry
        if (self.adj.nnz() != self.adj.t().nnz()):
            raise ImportError("The input adjacency matrix has to be symmetric.")
        
        self.edge_index = self.adj.to_torch_sparse_coo_tensor()._indices()

        if condition_key is not None:
            unique_conditions = adata.obs[condition_key].unique().tolist()
            condition_label_encoder = {k: v for k, v in zip(
                unique_conditions,
                range(len(unique_conditions)))}
            self.conditions = torch.tensor(
                encode_labels(adata,
                              condition_label_encoder,
                              condition_key), dtype=torch.long)

        self.n_node_features = self.x.size(1)
        self.size_factors = self.x.sum(1)

    def __len__(self):
        """Return the number of observations stored in SpatialAnnTorchDataset"""
        return self.x.size(0)