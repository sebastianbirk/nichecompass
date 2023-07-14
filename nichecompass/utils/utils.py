"""
This module contains helper functions for the ´utils´ subpackage.
"""

import os
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyreadr
import seaborn as sns


def load_R_file_as_df(R_file_path: str,
                      url: Optional[str]=None,
                      save_df_to_disk: bool=False,
                      df_save_path: Optional[str]=None) -> pd.DataFrame:
    """
    Helper to load an R file either from ´url´ if specified or from ´file_path´ 
    on disk and convert it to a pandas DataFrame.

    Parameters
    ----------
    R_file_path:
        File path to the R file to be loaded as df.
    url:
        URL of the R file to be loaded as df.
    save_df_to_disk:
        If ´True´, save df to disk.
    df_save_path:
        Path where the df will be saved if ´save_df_to_disk´ is ´True´.

    Returns
    ----------
    df:
        Content of R file loaded into a pandas DataFrame.
    """
    if url is None:
        if not os.path.exists(R_file_path):
            raise ValueError("Please specify a valid ´file_path´ or ´url´.")
        result_odict = pyreadr.read_r(R_file_path)
    else:
        result_odict = pyreadr.read_r(pyreadr.download_file(url, R_file_path))
        os.remove(R_file_path)

    df = result_odict[None]

    if save_df_to_disk:
        if df_save_path == None:
            raise ValueError("Please specify ´df_save_path´ or set " 
                             "´save_to_disk.´ to False.")
        df.to_csv(df_save_path)
    return df


def create_gp_gene_count_distribution_plots(gp_dict: dict,
                                            gp_dict_label: str):
    """
    Create distribution plots of the gene counts for sources and targets
    of all gene programs in the gp dict.

    Parameters
    ----------
    gp_dict:
        A gene program dictionary.
    gp_dict_label:
        Label of the gene program dictionary for plot title.
    """
    # Get number of source and target genes for each gene program
    n_sources_list = []
    n_targets_list = []
    for _, gp_sources_targets_dict in gp_dict.items():
        n_sources_list.append(len(gp_sources_targets_dict["sources"]))
        n_targets_list.append(len(gp_sources_targets_dict["targets"]))
    
    # Convert the arrays to a pandas DataFrame
    targets_df = pd.DataFrame({"values": n_targets_list})
    sources_df = pd.DataFrame({"values": n_sources_list})

    # Determine plot configurations
    max_n_targets = max(n_targets_list)
    max_n_sources = max(n_sources_list)
    if max_n_targets > 200:
        targets_x_ticks_range = 100
        xticklabels_rotation = 45  
    elif max_n_targets > 100:
        targets_x_ticks_range = 20
        xticklabels_rotation = 0
    elif max_n_targets > 10:
        targets_x_ticks_range = 10
        xticklabels_rotation = 0
    else:
        targets_x_ticks_range = 1
        xticklabels_rotation = 0
    if max_n_sources > 200:
        sources_x_ticks_range = 100   
    elif max_n_sources > 100:
        sources_x_ticks_range = 20
    elif max_n_sources > 10:
        sources_x_ticks_range = 10
    else:
        sources_x_ticks_range = 1

    # Create subplot
    fig, (ax1, ax2) = plt.subplots(ncols=2, figsize=(10, 5))
    plt.suptitle(
        f"{gp_dict_label} Gene Programs – Gene Count Distribution Plots")
    sns.histplot(x="values", data=targets_df, ax=ax1)
    ax1.set_title("Gene Program Targets Distribution",
                  fontsize=10)
    ax1.set(xlabel="Number of Targets",
            ylabel="Number of Gene Programs")
    ax1.set_xticks(
        np.arange(0,
                  max_n_targets + targets_x_ticks_range,
                  targets_x_ticks_range))
    ax1.set_xticklabels(
        np.arange(0,
                  max_n_targets + targets_x_ticks_range,
                  targets_x_ticks_range),
        rotation=xticklabels_rotation)
    sns.histplot(x="values", data=sources_df, ax=ax2)
    ax2.set_title("Gene Program Sources Distribution",
                  fontsize=10)
    ax2.set(xlabel="Number of Sources",
            ylabel="Number of Gene Programs")
    ax2.set_xticks(
        np.arange(0,
                  max_n_sources + sources_x_ticks_range,
                  sources_x_ticks_range))
    ax2.set_xticklabels(
        np.arange(0,
                  max_n_sources + sources_x_ticks_range,
                  sources_x_ticks_range),
        rotation=xticklabels_rotation)
    plt.subplots_adjust(wspace=0.35)
    plt.show()