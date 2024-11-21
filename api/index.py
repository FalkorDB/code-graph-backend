import os
import datetime
from api import *
from typing import Optional
from functools import wraps
from falkordb import FalkorDB
from dotenv import load_dotenv
from urllib.parse import urlparse
from .auto_complete import prefix_search
from flask import Flask, request, jsonify, abort

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Configure the logger
import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Function to verify the token
SECRET_TOKEN = os.getenv('SECRET_TOKEN')
def verify_token(token):
    return token == SECRET_TOKEN

# Decorator to protect routes with token authentication
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')  # Get token from header
        if not token or not verify_token(token):
            return jsonify(message="Unauthorized"), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/graph_entities', methods=['GET'])
@token_required  # Apply token authentication decorator
def graph_entities():
    """
    Endpoint to fetch sub-graph entities from a given repository.
    The repository is specified via the 'repo' query parameter.

    Returns:
        - 200: Successfully returns the sub-graph.
        - 400: Missing or invalid 'repo' parameter.
        - 500: Internal server error or database connection issue.
    """

    # Access the 'repo' parameter from the GET request
    repo = request.args.get('repo')

    if not repo:
        logging.error("Missing 'repo' parameter in request.")
        return jsonify({"status": "Missing 'repo' parameter"}), 400

    if not graph_exists(repo):
        logging.error(f"Missing project {repo}")
        return jsonify({"status": f"Missing project {repo}"}), 400

    try:
        # Initialize the graph with the provided repo and credentials
        g = Graph(repo)

        # Retrieve a sub-graph of up to 100 entities
        sub_graph = g.get_sub_graph(100)

        logging.info(f"Successfully retrieved sub-graph for repo: {repo}")
        response = {
            'status': 'success',
            'entities': sub_graph
        }

        return jsonify(response), 200

    except Exception as e:
        logging.error(f"Error retrieving sub-graph for repo '{repo}': {e}")
        return jsonify({"status": "Internal server error"}), 500


@app.route('/get_neighbors', methods=['POST'])
@token_required  # Apply token authentication decorator
def get_neighbors():
    """
    Endpoint to get neighbors of a nodes list in the graph.
    Expects 'repo' and 'node_ids' as body parameters.

    Returns:
        JSON response containing neighbors or error messages.
    """

    # Get JSON data from the request
    data = request.get_json()

    # Get query parameters
    repo    = data.get('repo')
    node_ids = data.get('node_ids')

    # Validate 'repo' parameter
    if not repo:
        logging.error("Repository name is missing in the request.")
        return jsonify({"status": "Repository name is required."}), 400

    # Validate 'node_id' parameter
    if not node_ids:
        logging.error("Node ID is missing in the request.")
        return jsonify({"status": "Node ID is required."}), 400

    # Validate repo exists
    if not graph_exists(repo):
        logging.error(f"Missing project {repo}")
        return jsonify({"status": f"Missing project {repo}"}), 400

    # Try converting node_id to an integer
    try:
        node_ids = [int(node_id) for node_id in node_ids]
    except ValueError:
        logging.error(f"Invalid node ID: {node_ids}. It must be an integer.")
        return jsonify({"status": "Invalid node ID. It must be an integer."}), 400

    # Initialize the graph with the provided repository
    g = Graph(repo)

    # Fetch the neighbors of the specified node
    neighbors = g.get_neighbors(node_ids)

    # Log and return the neighbors
    logging.info(f"Successfully retrieved neighbors for node ID {node_ids} in repo '{repo}'.")

    response = {
        'status': 'success',
        'neighbors': neighbors
    }

    return jsonify(response), 200

@app.route('/auto_complete', methods=['POST'])
@token_required  # Apply token authentication decorator
def auto_complete():
    """
    Endpoint to process auto-completion requests for a repository based on a prefix.

    Returns:
        JSON response with auto-completion suggestions or an error message.
    """

    # Get JSON data from the request
    data = request.get_json()

    # Validate that 'repo' is provided
    repo = data.get('repo')
    if repo is None:
        return jsonify({'status': f'Missing mandatory parameter "repo"'}), 400

    # Validate that 'prefix' is provided
    prefix = data.get('prefix')
    if prefix is None:
        return jsonify({'status': f'Missing mandatory parameter "prefix"'}), 400

    # Validate repo exists
    if not graph_exists(repo):
        return jsonify({'status': f'Missing project {repo}'}), 400

    # Fetch auto-completion results
    completions = prefix_search(repo, prefix)

    # Create a success response
    response = {
        'status': 'success',
        'completions': completions
    }

    return jsonify(response), 200

@app.route('/process_repo', methods=['POST'])
@token_required  # Apply token authentication decorator
def process_repo():
     """
     Process a GitHub repository.

     Expected JSON payload:
     {
         "repo_url": "string",
         "ignore": ["string"]  # optional
     }

     Returns:
         JSON response with processing status
     """

     data = request.get_json()
     url = data.get('repo_url')
     if url is None:
         return jsonify({'status': f'Missing mandatory parameter "url"'}), 400
     logger.debug(f'Received repo_url: {url}')

     ignore = data.get('ignore', [])

     proj = Project.from_git_repository(url)
     proj.analyze_sources(ignore)
    #  proj.process_git_history(ignore)

     # Create a response
     response = {
         'status': 'success',
     }

     return jsonify(response), 200


@app.route('/list_repos', methods=['GET'])
@token_required  # Apply token authentication decorator
def list_repos():
    """
    Endpoint to list all available repositories.

    Returns:
        JSON response with a list of repositories or an error message.
    """

    # Fetch list of repositories
    repos = get_repos()
    print(repos)
    # Create a success response with the list of repositories
    response = {
        'status': 'success',
        'repositories': repos
    }

    return jsonify(response), 200

@app.route('/repo_info', methods=['POST'])
@token_required  # Apply token authentication decorator
def repo_info():
    """
    Endpoint to retrieve information about a specific repository.

    Expected JSON payload:
        {
            "repo": <repository name>
        }

    Returns:
        JSON: A response containing the status and graph statistics (node and edge counts).
            - 'status': 'success' if successful, or an error message.
            - 'info': A dictionary with the node and edge counts if the request is successful.
    """

    # Get JSON data from the request
    data = request.get_json()

    # Validate the 'repo' parameter
    repo = data.get('repo')
    if repo is None:
        return jsonify({'status': f'Missing mandatory parameter "repo"'}), 400

    # Initialize the graph with the provided repository name
    g = Graph(repo)

    # Retrieve statistics from the graph
    stats = g.stats()
    info = get_repo_info(repo)

    if stats is None or info is None:
        return jsonify({'status': f'Missing repository "{repo}"'}), 400

    stats |= info 

    # Create a response
    response = {
        'status': 'success',
        'info': stats
    }

    return jsonify(response), 200

@app.route('/find_paths', methods=['POST'])
@token_required  # Apply token authentication decorator
def find_paths():
    """
    Finds all paths between a source node (src) and a destination node (dest) in the graph.
    The graph is associated with the repository (repo) provided in the request.

    Request Body (JSON):
        - repo (str): Name of the repository.
        - src (int): ID of the source node.
        - dest (int): ID of the destination node.

    Returns:
        A JSON response with:
        - status (str): Status of the request ("success" or "error").
        - paths (list): List of paths between the source and destination nodes.
    """

    # Get JSON data from the request
    data = request.get_json()

    # Validate 'repo' parameter
    repo = data.get('repo')
    if repo is None:
        return jsonify({'status': f'Missing mandatory parameter "repo"'}), 400

    # Validate 'src' parameter
    src = data.get('src')
    if src is None:
        return jsonify({'status': f'Missing mandatory parameter "src"'}), 400
    if not isinstance(src, int):
        return jsonify({'status': "src node id must be int"}), 400

    # Validate 'dest' parameter
    dest = data.get('dest')
    if dest is None:
        return jsonify({'status': f'Missing mandatory parameter "dest"'}), 400
    if not isinstance(dest, int):
        return jsonify({'status': "dest node id must be int"}), 400

    if not graph_exists(repo):
        logging.error(f"Missing project {repo}")
        return jsonify({"status": f"Missing project {repo}"}), 400

    # Initialize graph with provided repo and credentials
    g = Graph(repo)

    # Find paths between the source and destination nodes
    paths = g.find_paths(src, dest)

    # Create and return a successful response
    response = { 'status': 'success', 'paths': paths }

    return jsonify(response), 200

@app.route('/chat', methods=['POST'])
@token_required  # Apply token authentication decorator
def chat():
    # Get JSON data from the request
    data = request.get_json()

    # Validate 'repo' parameter
    repo = data.get('repo')
    if repo is None:
        return jsonify({'status': f'Missing mandatory parameter "repo"'}), 400

    # Get optional 'label' and 'relation' parameters
    msg = data.get('msg')
    if msg is None:
        return jsonify({'status': f'Missing mandatory parameter "msg"'}), 400

    answer = ask(repo, msg)

    # Create and return a successful response
    response = { 'status': 'success', 'response': answer }

    return jsonify(response), 200
