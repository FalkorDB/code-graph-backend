import os
import time
import json
import redis
import logging
import threading
import subprocess
from ..info import *
from git import Repo
from pathlib import Path
from ..graph import Graph
from .git_graph import GitGraph
from typing import List, Optional
from ..analyzers import SourceAnalyzer

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(filename)s - %(asctime)s - %(levelname)s - %(message)s')

def GitRepoName(repo_name):
    return "{" + repo_name + "}_git"

def is_ignored(file_path: str, ignore_list: List[str]) -> bool:
    """
    Checks if a file should be ignored based on the ignore list.

    Args:
        file_path (str): The file path to check.
        ignore_list (List[str]): List of patterns to ignore.

    Returns:
        bool: True if the file should be ignored, False otherwise.
    """

    return any(file_path.startswith(ignore) for ignore in ignore_list)

def classify_changes(diff, ignore_list: List[str]) -> (List[str], List[str], List[str]):
    """
    Classifies changes into added, deleted, and modified files.

    Args:
        diff: The git diff object representing changes between two commits.
        ignore_list (List[str]): List of file patterns to ignore.

    Returns:
        (List[str], List[str], List[str]): A tuple of lists representing added, deleted, and modified files.
    """

    added, deleted, modified = [], [], []

    for change in diff:
        if change.new_file and not is_ignored(change.b_path, ignore_list):
            logging.debug(f"new file: {change.b_path}")
            added.append(Path(change.b_path))
        if change.deleted_file and not is_ignored(change.a_path, ignore_list):
            logging.debug(f"deleted file: {change.a_path}")
            deleted.append(change.a_path)
        if change.change_type == 'M' and not is_ignored(change.a_path, ignore_list):
            logging.debug(f"change file: {change.a_path}")
            modified.append(Path(change.a_path))

    return added, deleted, modified

# build a graph capturing the git commit history
def build_commit_graph(
        path: str,
        repo_name: str,
        ignore_list: Optional[List[str]] = []
    ) -> GitGraph:
    """
    Builds a graph representation of the git commit history.

    Args:
        path (str): Path to the git repository.
        repo_name (str): Name of the repository.
        ignore_list (List[str], optional): List of file patterns to ignore.

    Returns:
        GitGraph: Graph object representing the commit history.
    """

    # Copy the graph into a temporary graph
    logging.info(f"Cloning source graph {repo_name} -> {repo_name}_tmp")
    # Will be deleted at the end of this function
    g = Graph(repo_name).clone(repo_name + "_tmp")
    g.enable_backlog()

    analyzer        = SourceAnalyzer()
    git_graph       = GitGraph(GitRepoName(repo_name))
    supported_types = analyzer.supported_types()

    # Initialize with the current commit
    # Save current git for later restoration
    repo = Repo('.')
    current_commit = repo.head.commit
    current_commit_hexsha = current_commit.hexsha

    # Add commit to the git graph
    git_graph.add_commit(current_commit)

    #--------------------------------------------------------------------------
    # Process git history going backwards
    #--------------------------------------------------------------------------

    logging.info("Computing transition queries moving backwards")

    child_commit = current_commit
    while len(child_commit.parents) > 0:
        parent_commit = child_commit.parents[0]

        # add commit to the git graph
        git_graph.add_commit(parent_commit)

        # connect child parent commits relation
        git_graph.connect_commits(child_commit.hexsha, parent_commit.hexsha)

        # Represents the changes going backward!
        # e.g. which files need to be deleted when moving back one commit
        #
        # if we were to switch "direction" going forward
        # delete events would become add event
        # e.g. which files need to be added when moving forward from this commit
        #      to the next one

        # Process file changes in this commit
        logging.info(f"""Computing diff between
            child {child_commit.hexsha}: {child_commit.message}
            and {parent_commit.hexsha}: {parent_commit.message}""")

        diff = child_commit.diff(parent_commit)
        added, deleted, modified = classify_changes(diff, ignore_list)

        # Checkout prev commit
        logging.info(f"Checking out commit: {parent_commit.hexsha}")
        repo.git.checkout(parent_commit.hexsha)

        #-----------------------------------------------------------------------
        # Apply changes going backwards
        #-----------------------------------------------------------------------

        # apply deletions
        # TODO: a bit of a waste, compute in previous loop
        deleted_files = []
        for deleted_file_path in deleted:
            _ext = os.path.splitext(deleted_file_path)[1]
            if _ext in supported_types:
                _path = os.path.dirname(deleted_file_path)
                _name = os.path.basename(deleted_file_path)
                deleted_files.append(
                        {'path': _path, 'name': _name, 'ext' : _ext})

        # remove deleted files from the graph
        if len(deleted_files) > 0:
            logging.info(f"Removing deleted files: {deleted_files}")
            g.delete_files(deleted_files)

        if len(added) > 0:
            for new_file in added:
                # New file been added
                logging.info(f"Introducing a new source file: {new_file}")
                analyzer.analyze_file(new_file, g)

        queries, params = g.clear_backlog()

        # Save transition queries to the git graph
        if len(queries) > 0:
            assert(len(queries) == len(params))

            # Covert parameters from dict to JSON formatted string
            params = [json.dumps(p) for p in params]

            # Log transitions
            logging.debug(f"""Save graph transition from
                             commit: {child_commit.hexsha}
                             to
                             commit: {parent_commit.hexsha}
                             Queries: {queries}
                             Parameters: {params}
                          """)

            git_graph.set_parent_transition(child_commit.hexsha,
                                            parent_commit.hexsha, queries, params)
        # advance to the next commit
        child_commit = parent_commit

    #--------------------------------------------------------------------------
    # Process git history going forward
    #--------------------------------------------------------------------------

    logging.info("Computing transition queries moving forward")
    parent_commit = child_commit
    while parent_commit.hexsha != current_commit_hexsha:
        child_commit = git_graph.get_child_commit(parent_commit.hexsha)
        child_commit = repo.commit(child_commit['hash'])

        # Represents the changes going forward
        # e.g. which files need to be deleted when moving forward one commit

        # Process file changes in this commit
        logging.info(f"""Computing diff between
            child {parent_commit.hexsha}: {parent_commit.message}
            and {child_commit.hexsha}: {child_commit.message}""")

        diff = parent_commit.diff(child_commit)
        added, deleted, modified = classify_changes(diff, ignore_list)

        # Checkout child commit
        logging.info(f"Checking out commit: {child_commit.hexsha}")
        repo.git.checkout(child_commit.hexsha)

        #-----------------------------------------------------------------------
        # Apply changes going forward
        #-----------------------------------------------------------------------

        # apply deletions
        # TODO: a bit of a waste, compute in previous loop
        deleted_files = []
        for deleted_file_path in deleted:
            _ext = os.path.splitext(deleted_file_path)[1]
            if _ext in supported_types:
                _path = os.path.dirname(deleted_file_path)
                _name = os.path.basename(deleted_file_path)
                deleted_files.append(
                        {'path': _path, 'name': _name, 'ext' : _ext})

        # remove deleted files from the graph
        if len(deleted_files) > 0:
            logging.info(f"Removing deleted files: {deleted_files}")
            g.delete_files(deleted_files)

        if len(added) > 0:
            for new_file in added:
                # New file been added
                logging.info(f"Introducing a new source file: {new_file}")
                analyzer.analyze_file(new_file, g)

        queries, params = g.clear_backlog()

        # Save transition queries to the git graph
        if len(queries) > 0:
            assert(len(queries) == len(params))

            # Covert parameters from dict to JSON formatted string
            params = [json.dumps(p) for p in params]

            # Log transitions
            logging.debug(f"""Save graph transition from
                             commit: {parent_commit.hexsha}
                             to
                             commit: {child_commit.hexsha}
                             Queries: {queries}
                             Parameters: {params}
                          """)

            git_graph.set_child_transition(child_commit.hexsha,
                                            parent_commit.hexsha, queries, params)
        # advance to the child_commit
        parent_commit = child_commit

    logging.debug("Done processing repository commit history")

    #--------------------------------------------------------------------------
    # Clean up
    #--------------------------------------------------------------------------

    # Delete temporaty graph
    g.disable_backlog()

    logging.debug(f"Deleting temporary graph {repo_name + '_tmp'}")
    g.delete()

    return git_graph

def switch_commit(repo: str, to: str) -> dict[str, dict[str, list]]:
    """
    Switches the state of a graph repository from its current commit to the given commit.

    This function handles switching between two git commits for a graph-based repository.
    It identifies the changes (additions, deletions, modifications) in nodes and edges between
    the current commit and the target commit and then applies the necessary transitions.

    Args:
        repo (str): The name of the graph repository to switch commits.
        to (str): The target commit hash to switch the graph to.

    Returns:
        dict: A dictionary containing the changes made during the commit switch, organized by:
            - 'deletions': {
                'nodes': List of node IDs deleted,
                'edges': List of edge IDs deleted
            },
            - 'additions': {
                'nodes': List of new Node objects added,
                'edges': List of new Edge objects added
            },
            - 'modifications': {
                'nodes': List of modified Node objects,
                'edges': List of modified Edge objects
            }
    """

    # Validate input arguments
    if not repo or not isinstance(repo, str):
        raise ValueError("Invalid repository name")

    if not to or not isinstance(to, str):
        raise ValueError("Invalid desired commit value")

    logging.info(f"Switching to commit: {to}")

    # Initialize return value to an empty change set
    change_set = {
        'deletions': {
            'nodes': [],
            'edges': []
        },
        'additions': {
            'nodes': [],
            'edges': [],
        },
        'modifications': {
            'nodes': [],
            'edges': []
        }
    }

    # Initialize the graph and GitGraph objects
    g = Graph(repo)
    git_graph = GitGraph(GitRepoName(repo))

    # Get the current commit hash of the graph
    current_hash = get_repo_commit(repo)
    logging.info(f"Current graph commit: {current_hash}")

    if current_hash == to:
        logging.debug("Current commit: {current_hash} is the requested commit")
        # No change remain at the current commit
        return change_set

    # Find the path between the current commit and the desired commit
    commits = git_graph.get_commits([current_hash, to])

    # Ensure both current and target commits are present
    if len(commits) != 2:
        logging.error("Missing commits. Unable to proceed.")
        raise ValueError("Commits not found")

    # Identify the current and new commits based on their hashes
    current_commit, new_commit = (commits if commits[0]['hash'] == current_hash else reversed(commits))

    # Determine the direction of the switch (forward or backward in the commit history)
    child_commit = None
    parent_commit = None
    if current_commit['date'] > new_commit['date']:
        child_commit  = current_commit
        parent_commit = new_commit
        logging.info(f"Moving backward from {child_commit['hash']} to {parent_commit['hash']}")
        # Get the transitions (queries and parameters) for moving backward
        queries, params = git_graph.get_parent_transitions(child_commit['hash'], parent_commit['hash'])
    else:
        child_commit  = new_commit
        parent_commit = current_commit
        logging.info(f"Moving forward from {parent_commit['hash']} to {child_commit['hash']}")
        # Get the transitions (queries and parameters) for moving forward
        queries, params = git_graph.get_child_transitions(child_commit['hash'], parent_commit['hash'])

    # Apply each transition query with its respective parameters
    for q, p in zip(queries, params):
        for _q, _p in zip(q, p):
            _p = json.loads(_p)
            logging.debug(f"Executing query: {_q} with params: {_p}")

            # Rerun the query with parameters on the graph
            res = g.rerun_query(_q, _p)
            if "DELETE" in _q:
                deleted_nodes = res.result_set[0][0]
                change_set['deletions']['nodes'] += deleted_nodes

    # Update the graph's commit to the new target commit
    set_repo_commit(repo, to)
    logging.info(f"Graph commit updated to {to}")

    return change_set

