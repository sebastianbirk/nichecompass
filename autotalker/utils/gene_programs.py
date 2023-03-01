"""
This module contains utiilities to add interpretable communication gene programs
as prior knowledge for use by the Autotalker model.
"""

from typing import Literal, Optional

import numpy as np
import omnipath as op
import pandas as pd
from anndata import AnnData

from .utils import load_R_file_as_df, create_gp_gene_count_distribution_plots


def add_gps_from_gp_dict_to_adata(
        gp_dict: dict,
        adata: AnnData,
        genes_uppercase: bool=True,
        gp_targets_mask_key: str="autotalker_gp_targets",
        gp_sources_mask_key: str="autotalker_gp_sources",
        gp_names_key: str="autotalker_gp_names",
        source_genes_idx_key: str="autotalker_source_genes_idx",
        target_genes_idx_key: str="autotalker_target_genes_idx",
        genes_idx_key: str="autotalker_genes_idx",
        min_genes_per_gp: int=1,
        min_source_genes_per_gp: int=0,
        min_target_genes_per_gp: int=0,
        max_genes_per_gp: Optional[int]=None,
        max_source_genes_per_gp: Optional[int]=None,
        max_target_genes_per_gp: Optional[int]=None,
        filter_genes_not_in_masks: bool=False):
    """
    Add gene programs defined in a gene program dictionary to an AnnData object
    by converting the gene program lists of gene program target and source genes
    to binary masks and aligning the masks with genes for which gene expression
    is available in the AnnData object.

    Parts of the implementation are inspired by
    https://github.com/theislab/scarches/blob/master/scarches/utils/annotations.py#L5
    (01.10.2022).

    Parameters
    ----------
    gp_dict:
        Nested dictionary containing the gene programs with keys being gene 
        program names and values being dictionaries with keys ´targets´ and 
        ´sources´, where ´targets´ contains a list of the names of genes in the
        gene program for the reconstruction of the gene expression of the node
        itself (receiving node) and ´sources´ contains a list of the names of
        genes in the gene program for the reconstruction of the gene expression
        of the node's neighbors (transmitting nodes).
    adata:
        AnnData object to which the gene programs will be added.
    genes_uppercase:
        If `True`, convert the gene names in adata to uppercase for comparison
        with the gene program dictionary (e.g. if adata contains mouse data).
    gp_targets_mask_key:
        Key in ´adata.varm´ where the binary gene program mask for target genes
        of a gene program will be stored (target genes are used for the 
        reconstruction of the gene expression of the node itself (receiving node
        )).
    gp_sources_mask_key:
        Key in ´adata.varm´ where the binary gene program mask for source genes
        of a gene program will be stored (source genes are used for the 
        reconstruction of the gene expression of the node's neighbors 
        (transmitting nodes)).
    gp_names_key:
        Key in ´adata.uns´ where the gene program names will be stored.
    source_genes_idx_key:
        Key in ´adata.uns´ where the index of the source genes that are in the
        gene program mask will be stored.
    target_genes_idx_key:
        Key in ´adata.uns´ where the index of the target genes that are in the
        gene program mask will be stored.
    genes_idx_key:
        Key in ´adata.uns´ where the index of a concatenated vector of target
        and source genes that are in the gene program masks will be stored.
    min_genes_per_gp:
        Minimum number of genes in a gene program inluding both target and 
        source genes that need to be available in the adata (gene expression has
        been probed) for a gene program not to be discarded.
    min_source_genes_per_gp:
        Minimum number of source genes in a gene program that need to be 
        available in the adata (gene expression has been probed) for a gene 
        program not to be discarded.
    min_target_genes_per_gp:
        Minimum number of target genes in a gene program that need to be 
        available in the adata (gene expression has been probed) for a gene 
        program not to be discarded.
    max_genes_per_gp:
        Maximum number of genes in a gene program inluding both target and 
        source genes that can be available in the adata (gene expression has 
        been probed) for a gene program not to be discarded.
    max_source_genes_per_gp:
        Maximum number of source genes in a gene program that can be available 
        in the adata (gene expression has been probed) for a gene program not to
        be discarded.
    max_target_genes_per_gp:
        Maximum number of target genes in a gene program that can be available 
        in the adata (gene expression has been probed) for a gene program not to
        be discarded.
    filter_genes_not_in_masks:
        If ´True´, remove the genes that are not in the gp masks from the adata
        object.
    """
    # Retrieve probed genes from adata
    adata_genes = (adata.var_names.str.upper() if genes_uppercase
                   else adata.var_names)

    # Create binary gene program masks considering only probed genes
    gp_targets_mask = [[int(gene in gp_genes_dict["targets"])
                        for _, gp_genes_dict in gp_dict.items()]
                       for gene in adata_genes]
    gp_targets_mask = np.asarray(gp_targets_mask, dtype="int32")
    gp_sources_mask = [[int(gene in gp_genes_dict["sources"])
                        for _, gp_genes_dict in gp_dict.items()]
                       for gene in adata_genes]
    gp_sources_mask = np.asarray(gp_sources_mask, dtype="int32")
    gp_mask = np.concatenate((gp_sources_mask, gp_targets_mask), axis=0)

    # Filter gene programs for min genes and max genes
    gp_mask_filter = gp_mask.sum(0) >= min_genes_per_gp
    if max_genes_per_gp is not None:
        gp_mask_filter &= gp_mask.sum(0) <= max_genes_per_gp
    gp_targets_mask_filter = gp_targets_mask.sum(0) >= min_target_genes_per_gp
    if max_target_genes_per_gp is not None:
        gp_targets_mask_filter &= (gp_targets_mask.sum(0)
                                   <= max_target_genes_per_gp)
    gp_sources_mask_filter = gp_sources_mask.sum(0) >= min_source_genes_per_gp
    if max_source_genes_per_gp is not None:
        gp_sources_mask_filter &= (gp_sources_mask.sum(0)
                                   <= max_source_genes_per_gp)
    gp_mask_filter &= gp_sources_mask_filter
    gp_mask_filter &= gp_targets_mask_filter
    gp_targets_mask = gp_targets_mask[:, gp_mask_filter]
    gp_sources_mask = gp_sources_mask[:, gp_mask_filter]

    # Add binary gene program masks to ´adata.varm´
    adata.varm[gp_sources_mask_key] = gp_sources_mask
    adata.varm[gp_targets_mask_key] = gp_targets_mask

    if filter_genes_not_in_masks:
        # Filter out genes not present in any of the masks
        combined_gp_mask = np.maximum(adata.varm["autotalker_gp_sources"],
                                      adata.varm["autotalker_gp_targets"])
        adata._inplace_subset_var(combined_gp_mask.sum(axis=1) > 0)

    # Get index of genes present in the sources and targets mask respectively
    adata.uns[source_genes_idx_key] = np.nonzero(
        adata.varm[gp_sources_mask_key].sum(axis=1))[0]
    adata.uns[target_genes_idx_key] = np.nonzero(
        adata.varm[gp_targets_mask_key].sum(axis=1))[0]
    adata.uns[genes_idx_key] = np.concatenate(
        (adata.uns[target_genes_idx_key],
         adata.uns[source_genes_idx_key] + adata.n_vars), axis=0)
         
    # Add gene program names of gene programs that passed filter to adata.uns
    removed_gp_idx = np.where(~gp_mask_filter)[0]
    adata.uns[gp_names_key] = np.array([gp_name for i, (gp_name, _) in 
                                        enumerate(gp_dict.items()) if i not in 
                                        removed_gp_idx])


def extract_gp_dict_from_nichenet_ligand_target_mx(
        keep_target_genes_ratio: float=0.,
        max_n_target_genes_per_gp: int=100,
        load_from_disk: bool=False,
        save_to_disk: bool=False,
        file_path: Optional[str]="nichenet_ligand_target_matrix.csv",
        plot_gp_gene_count_distributions: bool=True) -> dict:
    """
    Retrieve NicheNet ligand target potential matrix as described in Browaeys, 
    R., Saelens, W. & Saeys, Y. NicheNet: modeling intercellular communication 
    by linking ligands to target genes. Nat. Methods 17, 159–162 (2020) and 
    extract a gene program dictionary from the matrix based on 
    ´keep_target_ratio´.

    Parameters
    ----------
    keep_target_genes_ratio:
        Ratio of target genes that are kept compared to total target genes. This
        ratio is applied over the entire matrix (not on gene program level) and
        determines the ´score_keep_threshold´, which will be used to filter 
        target genes according to their scores.
    max_n_target_genes_per_gp:
        Maximum number of target genes per gene program. If a gene program has
        more target genes than ´max_n_target_genes_per_gp´, only the
        ´max_n_target_genes_per_gp´ gene programs with the highest scores will
        be kept.
    load_from_disk:
        If ´True´, the NicheNet ligand target matrix will be loaded from disk
        instead of from the web.
    save_to_disk:
        If ´True´, the NicheNet ligand target matrix will additionally be stored
        on disk.
    file_path:
        Path of the file where the NicheNet ligand target matrix will be stored
        (if ´save_to_disk´ is ´True´) or loaded from (if ´load_from_disk´ is
        ´True´).
    plot_gp_gene_count_distributions:
        If ´True´, display the distribution of gene programs per number of
        target and source genes.

    Returns
    ----------
    gp_dict:
        Nested dictionary containing the NicheNet ligand target genes gene 
        programs with keys being gene program names and values being 
        dictionaries with keys ´targets´ and ´sources´, where ´targets´ contains
        the NicheNet target genes and ´sources´ contains the NicheNet ligands.
    """
    # Download or load NicheNet ligand target matrix and store in df (optionally
    # also on disk)
    if not load_from_disk:
        print("Downloading NicheNet ligand target potential matrix from the "
              "web. This might take a while...")
        ligand_target_df = load_R_file_as_df(
            R_file_path="ligand_target_matrix.rds",
            url="https://zenodo.org/record/3260758/files/ligand_target_matrix.rds",
            save_df_to_disk=save_to_disk,
            df_save_path=file_path)
    else:
        ligand_target_df = pd.read_csv(file_path, index_col=0)

    # Filter NicheNet ligand target matrix based on scores and
    # ´keep_target_genes_ratio´ and ´max_n_target_genes_per_gp´
    per_gp_target_gene_scores = ligand_target_df.values.copy()
    all_target_gene_scores = np.squeeze(per_gp_target_gene_scores).flatten()
    per_gp_target_gene_scores_sorted = np.flip(
        np.sort(per_gp_target_gene_scores, axis=0), axis=0)
    per_gp_score_keep_threshold = pd.Series(
        per_gp_target_gene_scores_sorted[max_n_target_genes_per_gp, :],
        index=ligand_target_df.columns)
    all_target_gene_scores.sort()
    all_target_gene_scores_sorted = np.flip(all_target_gene_scores)
    all_gps_score_keep_threshold = all_target_gene_scores_sorted[int(
        (len(all_target_gene_scores_sorted) - 1) * keep_target_genes_ratio)]
    ligand_target_all_gps_score_keep_threshold_mask_df = (
        ligand_target_df.applymap(lambda x: x > all_gps_score_keep_threshold))
    ligand_target_per_gp_score_keep_threshold_mask_df = ligand_target_df.apply(
        lambda col: col > per_gp_score_keep_threshold[col.name], axis=0)
    ligand_target_combined_keep_threshold_mask_df = (
        ligand_target_all_gps_score_keep_threshold_mask_df &
        ligand_target_per_gp_score_keep_threshold_mask_df)

    # Extract gene programs and store in nested dict
    ligand_target_mask_dict = (
        ligand_target_combined_keep_threshold_mask_df.to_dict())
    gp_dict = {}
    for ligand in ligand_target_mask_dict.keys():
        gp_dict[ligand + "_ligand_targetgenes_GP"] = {
            "sources": [ligand],
            "targets": [target for target, include in
                        ligand_target_mask_dict[ligand].items() if include]}
        
    if plot_gp_gene_count_distributions:
        create_gp_gene_count_distribution_plots(gp_dict)

    return gp_dict


def extract_gp_dict_from_omnipath_lr_interactions(
        min_curation_effort: int=0,
        load_from_disk: bool=False,
        save_to_disk: bool=False,
        file_path: Optional[str]="omnipath_lr_interactions.csv",
        plot_gp_gene_count_distributions: bool=True) -> dict:
    """
    Retrieve ligand-receptor interactions from OmniPath and extract them into a 
    gene program dictionary. OmniPath is a database of molecular biology prior 
    knowledge that combines intercellular communication data from many different
    resources (all resources for intercellular communication included in 
    OmniPath can be queried via ´op.requests.Intercell.resources()´).

    Parts of the implementation are inspired by 
    https://workflows.omnipathdb.org/intercell-networks-py.html (01.10.2022).

    Parameters
    ----------
    min_curation_effort: 
        Indicates how many times an interaction has to be described in a 
        paper and mentioned in a database to be included in the retrieval.
    load_from_disk:
        If ´True´, the OmniPath ligand-receptor interactions will be loaded from
        disk instead of from the omnipath library.
    save_to_disk:
        If ´True´, the OmniPath ligand-receptor interactions will additionally 
        be stored on disk. Only applies if ´load_from_disk´ is ´False´.
    file_path:
        Path of the file where the OmniPath ligand-receptor interactions will be
        stored (if ´save_to_disk´ is ´True´) or loaded from (if ´load_from_disk´
        is ´True´).
    plot_gp_gene_count_distributions:
        If ´True´, display the distribution of gene programs per number of
        target and source genes.

    Returns
    ----------
    gp_dict:
        Nested dictionary containing the OmniPath ligand-receptor interaction
        gene programs with keys being gene program names and values being 
        dictionaries with keys ´targets´ and ´sources´, where ´targets´ contains
        the OmniPath receptors and ´sources´ contains the OmniPath ligands.
    """
    if not load_from_disk:
        # Define intercell_network categories to be retrieved
        intercell_df = op.interactions.import_intercell_network(
            include=["omnipath", "pathwayextra", "ligrecextra"])
        # Set transmitters to be ligands and receivers to be receptors
        lr_interaction_df = intercell_df[
            (intercell_df["category_intercell_source"] == "ligand")
            & (intercell_df["category_intercell_target"] == "receptor")]
        if save_to_disk:
            lr_interaction_df.to_csv(file_path, index=False)
    else:
        lr_interaction_df = pd.read_csv(file_path, index_col=0)

    # Filter as per ´min_curation_effort´
    lr_interaction_df = lr_interaction_df[
        lr_interaction_df["curation_effort"] >= min_curation_effort]

    lr_interaction_df = lr_interaction_df[
        ["genesymbol_intercell_source", "genesymbol_intercell_target"]]
    lr_interaction_dict = lr_interaction_df.set_index(
        "genesymbol_intercell_source")["genesymbol_intercell_target"].to_dict()

    # Dictionary comprehension to convert dictionary values to lists and split
    # "COMPLEX:receptor1_receptor2" into ["receptor1", "receptor2"]
    lr_interaction_dict = {key: ([value] if "COMPLEX:" not in value
                                 else value.removeprefix("COMPLEX:").split("_"))
                           for key, value in lr_interaction_dict.items()}

    # Extract gene programs and store in nested dict
    gp_dict = {}
    for ligand, receptor in lr_interaction_dict.items():
        gp_dict[ligand + "_ligand_receptor_GP"] = {
            "sources": [ligand],
            "targets": receptor}
        
    if plot_gp_gene_count_distributions:
        create_gp_gene_count_distribution_plots(gp_dict)

    return gp_dict


def extract_gp_dict_from_mebocost_es_interactions(
        dir_path: str="../datasets/gp_data/metabolite_enzyme_sensor_gps/",
        species: Literal["mouse", "human"]="mouse",
        genes_uppercase: bool=False,
        plot_gp_gene_count_distributions: bool=True) -> dict:
    """
    Retrieve metabolite enzyme-sensor interactions from the Human Metabolome
    Database (HMDB) data curated in Chen, K. et al. MEBOCOST: 
    Metabolite-mediated cell communication modeling by single cell 
    transcriptome. Research Square (2022) doi:10.21203/rs.3.rs-2092898/v1. 
    This data is available in the Autotalker package under 
    ´datasets/gp_data/metabolite_enzyme_sensor_gps´.

    Parameters
    ----------
    species:
        Species for which to retrieve metabolite enzyme-sensor interactions.
    genes_uppercase:
        If `True`, convert the gene names to uppercase (e.g. to align with other
        gene programs that contain uppercase genes).
    plot_gp_gene_count_distributions:
        If ´True´, display the distribution of gene programs per number of
        target and source genes.

    Returns
    ----------
    gp_dict:
        Nested dictionary containing the MEBOCOST enzyme-sensor interaction
        gene programs with keys being gene program names and values being 
        dictionaries with keys ´targets´ and ´sources´, where ´targets´ contains
        the MEBOCOST sensor genes and ´sources´ contains the MEBOCOST enzyme
        genes.    
    """
    # Read data from directory
    if species == "human":
        metabolite_enzymes_df = pd.read_csv(
            dir_path + "human_metabolite_enzymes.tsv", sep="\t")
        metabolite_sensors_df = pd.read_csv(
            dir_path + "human_metabolite_sensors.tsv", sep="\t")
    elif species == "mouse":
        metabolite_enzymes_df = pd.read_csv(
            dir_path + "mouse_metabolite_enzymes.tsv", sep="\t")
        metabolite_sensors_df = pd.read_csv(
            dir_path + "mouse_metabolite_sensors.tsv", sep="\t")
    else:
        raise ValueError("Species should be either human or mouse.")

    # Retrieve metabolite names
    metabolite_names_df = (metabolite_sensors_df[["HMDB_ID",
                                                  "standard_metName"]]
                           .drop_duplicates()
                           .set_index("HMDB_ID"))

    # Retrieve metabolite enzyme and sensor genes
    metabolite_enzymes_unrolled = []
    for _, line in metabolite_enzymes_df.iterrows():
        genes = line["gene"].split("; ")
        for gene in genes:
            tmp = line.copy()
            tmp["gene"] = gene
            metabolite_enzymes_unrolled.append(tmp)
    metabolite_enzymes_df = pd.DataFrame(metabolite_enzymes_unrolled)
    metabolite_enzymes_df["gene_name"] = metabolite_enzymes_df["gene"].apply(
        lambda x: x.split("[")[0])
    metabolite_enzymes_df["gene_name"] = (metabolite_enzymes_df["gene_name"]
                                          .apply(lambda x: x.upper()
                                                 if genes_uppercase else x))
    metabolite_sensors_df["Gene_name"] = (metabolite_sensors_df["Gene_name"]
                                          .apply(lambda x: x.upper()
                                                 if genes_uppercase else x))
    metabolite_enzymes_df = (metabolite_enzymes_df.groupby(["HMDB_ID"])
                             .agg({"gene_name": lambda x: sorted(
                                x.unique().tolist())})
                             .rename({"gene_name": "enzyme_genes"}, axis=1)
                             .reset_index()).set_index("HMDB_ID")
    metabolite_sensors_df = (metabolite_sensors_df.groupby(["HMDB_ID"])
                             .agg({"Gene_name": lambda x: sorted(
                                x.unique().tolist())})
                             .rename({"Gene_name": "sensor_genes"}, axis=1)
                             .reset_index()).set_index("HMDB_ID")

    # Combine metabolite names and enzyme and sensor genes
    metabolite_df = metabolite_enzymes_df.join(
        other=metabolite_sensors_df,
        how="inner").join(metabolite_names_df).set_index("standard_metName")

    # Convert to gene program dictionary format
    met_interaction_dict = metabolite_df.to_dict()
    gp_dict = {}
    for metabolite, enzyme_genes in met_interaction_dict["enzyme_genes"].items():
        gp_dict[metabolite + "_metabolite_enzyme_sensor_GP"] = {
            "sources": enzyme_genes}
    for metabolite, sensor_genes in met_interaction_dict["sensor_genes"].items():
        gp_dict[metabolite + "_metabolite_enzyme_sensor_GP"][
            "targets"] = sensor_genes

    if plot_gp_gene_count_distributions:
        create_gp_gene_count_distribution_plots(gp_dict)

    return gp_dict


def filter_and_combine_gp_dict_gps(
        gp_dict: dict,
        gp_filter_mode: Optional[Literal["subset", "superset"]]=None,
        combine_overlap_gps: bool=True,
        overlap_thresh_source_genes: float=1.,
        overlap_thresh_target_genes: float=1.,
        overlap_thresh_genes: float=1.,
        verbose: bool=False) -> dict:
    """
    Parameters
    ----------
    gp_dict:
        Nested dictionary containing the gene programs with keys being gene 
        program names and values being dictionaries with keys ´targets´ and 
        ´sources´, where ´targets´ contains a list of the names of genes in the
        gene program for the reconstruction of the gene expression of the node
        itself (receiving node) and ´sources´ contains a list of the names of
        genes in the gene program for the reconstruction of the gene expression
        of the node's neighbors (transmitting nodes).
    gp_filter_mode:
        If `None` (default), do not filter any gene programs. If `subset`, 
        remove gene programs that are subsets of other gene programs from the 
        gene program dictionary. If `superset`, remove gene programs that are 
        supersets of other gene programs instead.
    combine_overlap_gps:
        If `True`, combine gene programs that overlap according to the defined
        thresholds.
    overlap_thresh_source_genes:
        If `combine_overlap_gps` is `True`, the minimum ratio of source 
        genes that need to overlap between two gene programs for them to be 
        combined.
    overlap_thresh_target_genes:
        If `combine_overlap_gps` is `True`, the minimum ratio of target 
        genes that need to overlap between two gene programs for them to be 
        combined.
    overlap_thresh_genes:
        If `combine_overlap_gps` is `True`, the minimum ratio of total genes
        (source genes & target genes) that need to overlap between two gene 
        programs for them to be combined.
    verbose:
        If `True`, print gene programs that are removed and combined.

    Returns
    ----------
    new_gp_dict:
        Modified gene program dictionary with gene programs filtered according 
        to ´gp_filter_mode´ and combined according to ´combine_overlap_gps´,
        ´overlap_thresh_source_genes´, ´overlap_thresh_target_genes´, and 
        ´overlap_thresh_genes´.
    """
    new_gp_dict = gp_dict.copy()

    # Remove gps that are subsets or supersets of other gps from the gp dict
    if gp_filter_mode != None:
        for i, (gp_i, gp_genes_dict_i) in enumerate(gp_dict.items()):
            source_genes_i = set([gene.upper() for gene in 
                                  gp_genes_dict_i["sources"]])
            target_genes_i = set([gene.upper() for gene in 
                                  gp_genes_dict_i["targets"]])
            for j, (gp_j, gp_genes_dict_j) in enumerate(gp_dict.items()):
                if i != j:
                    source_genes_j = set([gene.upper() for gene in 
                                          gp_genes_dict_j["sources"]])
                    target_genes_j = set([gene.upper() for gene in
                                          gp_genes_dict_j["targets"]])
                    if gp_filter_mode == "subset":
                        if (source_genes_j.issubset(source_genes_i) &
                            target_genes_j.issubset(target_genes_i)):
                                new_gp_dict.pop(gp_j, None)
                                if verbose:
                                    print(f"Removing GP '{gp_j}' as it is a "
                                          f"subset of GP '{gp_i}'.")
                    elif gp_filter_mode == "superset":
                        if (source_genes_j.issuperset(source_genes_i) &
                            target_genes_j.issuperset(target_genes_i)):
                                new_gp_dict.pop(gp_j, None)
                                if verbose:
                                    print(f"Removing GP '{gp_j}' as it is a "
                                          f"superset of GP '{gp_i}'.")

    # Combine overlap gps in the gp dict (overlap ratios are calculated 
    # based on average gene numbers of the compared gene programs)
    if combine_overlap_gps:
        # First, get all overlap gps per gene program (this includes
        # duplicate overlaps and unresolved cross overlaps (i.e. GP A might 
        # overlap with GP B and GP B might overlap with GP C while GP A and GP C
        # do not overlap)
        all_overlap_gps = []
        for i, (gp_i, gp_genes_dict_i) in enumerate(new_gp_dict.items()):
            source_genes_i = set([gene.upper() for gene in 
                                  gp_genes_dict_i["sources"]])
            target_genes_i = set([gene.upper() for gene in 
                                  gp_genes_dict_i["targets"]])
            gp_overlap_gps = [gp_i]
            for j, (gp_j, gp_genes_dict_j) in enumerate(new_gp_dict.items()):
                if i != j:
                    source_genes_j = set([gene.upper() for gene in 
                                          gp_genes_dict_j["sources"]])
                    target_genes_j = set([gene.upper() for gene in
                                          gp_genes_dict_j["targets"]])
                    source_genes_overlap = list(source_genes_i & source_genes_j)
                    target_genes_overlap = list(target_genes_i & target_genes_j)
                    n_source_gene_overlap = len(source_genes_overlap)
                    n_target_gene_overlap = len(target_genes_overlap)
                    n_gene_overlap = (n_source_gene_overlap + 
                                      n_target_gene_overlap)
                    n_avg_source_genes = (len(source_genes_i) + 
                                          len(source_genes_j)) / 2
                    n_avg_target_genes = (len(target_genes_i) + 
                                          len(target_genes_j)) / 2
                    n_avg_genes = n_avg_source_genes + n_avg_target_genes
                    if n_avg_source_genes > 0:
                        ratio_shared_source_genes = (n_source_gene_overlap / 
                                                     n_avg_source_genes)
                    else: 
                        ratio_shared_source_genes = 1
                    if n_avg_target_genes > 0:
                        ratio_shared_target_genes = (n_target_gene_overlap /
                                                     n_avg_target_genes)
                    else:
                        ratio_shared_target_genes = 1
                    ratio_shared_genes = n_gene_overlap / n_avg_genes
                    if ((ratio_shared_source_genes >= 
                         overlap_thresh_source_genes) &
                        (ratio_shared_target_genes >= 
                         overlap_thresh_target_genes) &
                        (ratio_shared_genes >= overlap_thresh_genes)):
                            gp_overlap_gps.append(gp_j)
            if len(gp_overlap_gps) > 1:
                all_overlap_gps.append(set(gp_overlap_gps))

        # Second, clean up duplicate overlaps 
        all_unique_overlap_gps = []
        _ = [all_unique_overlap_gps.append(overlap_gp) for overlap_gp in 
             all_overlap_gps if overlap_gp not in all_unique_overlap_gps]

        # Third, split overlaps into no cross and cross overlaps
        no_cross_overlap_gps = []
        cross_overlap_gps = []
        for i, overlap_gp_i in enumerate(all_unique_overlap_gps):
            if all(overlap_gp_j.isdisjoint(overlap_gp_i) for 
            j, overlap_gp_j in enumerate(all_unique_overlap_gps) 
            if i != j):
                no_cross_overlap_gps.append(overlap_gp_i)
            else:
                cross_overlap_gps.append(overlap_gp_i)

        # Fourth, resolve cross overlaps by sequentally combining them (until
        # convergence)
        sequential_overlap_gps = list(cross_overlap_gps)
        while True:
            new_sequential_overlap_gps = []
            for i, overlap_gp_i in enumerate(sequential_overlap_gps):
                paired_overlap_gps = [overlap_gp_i.union(overlap_gp_j) for 
                                      j, overlap_gp_j in 
                                      enumerate(sequential_overlap_gps) 
                                      if (i != j) & 
                                      (overlap_gp_i.intersection(overlap_gp_j) 
                                       != set())]
                paired_overlap_gps_union = set().union(*paired_overlap_gps)
                if (paired_overlap_gps_union != set() &
                paired_overlap_gps_union not in new_sequential_overlap_gps):
                    new_sequential_overlap_gps.append(paired_overlap_gps_union)
            if (sorted([list(gp) for gp in new_sequential_overlap_gps]) == 
            sorted([list(gp) for gp in sequential_overlap_gps])):
                break
            else:
                sequential_overlap_gps = list(new_sequential_overlap_gps)

        # Fifth, add overlap gps to gp dict and remove component gps
        final_overlap_gps = [list(overlap_gp) for overlap_gp in 
                             no_cross_overlap_gps]
        _ = [final_overlap_gps.append(list(overlap_gp)) for overlap_gp in 
             sequential_overlap_gps if list(overlap_gp) not in 
             final_overlap_gps]

        for overlap_gp in final_overlap_gps:
            new_gp_name = "_".join([gp[:-3] for gp in overlap_gp]) + "_GP"
            new_gp_sources = []
            new_gp_targets = []
            for gp in overlap_gp:
                new_gp_sources.extend(gp_dict[gp]["sources"])
                new_gp_targets.extend(gp_dict[gp]["targets"])
                new_gp_dict.pop(gp, None)
                if verbose:
                    print(f"Removing GP '{gp}' as it is a component of the "
                          f"combined GP '{new_gp_name}'.")
            new_gp_dict[new_gp_name] = {"sources": 
                                        sorted(list(set(new_gp_sources)))}
            new_gp_dict[new_gp_name]["targets"] = sorted(
                list(set(new_gp_targets)))
    return new_gp_dict


def get_unique_genes_from_gp_dict(
        gp_dict: dict,
        retrieved_gene_entities: list=["sources", "targets"]) -> list:
    """
    Return all unique genes of a gene program dictionary.

    Parameters
    ----------
    gp_dict:
        The gene program dictionary from which to retrieve the unique genes.
    retrieved_gene_entities:
        A list that contains all gene entities ("sources", "targets")
        for which unique genes of the gene program dictionary should be
        retrieved.

    Returns
    ----------
    unique_genes:
        A list of unique genes used in the gene program dictionary.
    """
    gene_list = []

    for _, gp in gp_dict.items():
        for gene_entity, genes in gp.items():
            if gene_entity in retrieved_gene_entities:
                gene_list.extend(genes)
    unique_genes = list(set(gene_list))
    unique_genes.sort()
    return unique_genes