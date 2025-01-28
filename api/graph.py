import os
import time
from .entities import *
from typing import Optional
from falkordb import FalkorDB, Path, Node, QueryResult

# Configure the logger
import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(filename)s - %(asctime)s - %(levelname)s - %(message)s')

def graph_exists(name: str):
    db = FalkorDB(host=os.getenv('FALKORDB_HOST', 'localhost'),
                  port=os.getenv('FALKORDB_PORT', 6379),
                  username=os.getenv('FALKORDB_USERNAME', None),
                  password=os.getenv('FALKORDB_PASSWORD', None))

    return name in db.list_graphs()

def get_repos() -> list[str]:
    """
        List processed repositories
    """

    db = FalkorDB(host=os.getenv('FALKORDB_HOST', 'localhost'),
                  port=os.getenv('FALKORDB_PORT', 6379),
                  username=os.getenv('FALKORDB_USERNAME', None),
                  password=os.getenv('FALKORDB_PASSWORD', None))

    graphs = db.list_graphs()
    graphs = [g for g in graphs if not (g.endswith('_git') or g.endswith('_schema'))]
    return graphs

class Graph():
    """
    Represents a connection to a graph database using FalkorDB.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.db = FalkorDB(host=os.getenv('FALKORDB_HOST', 'localhost'),
                           port=os.getenv('FALKORDB_PORT', 6379),
                           username=os.getenv('FALKORDB_USERNAME', None),
                           password=os.getenv('FALKORDB_PASSWORD', None))
        self.g = self.db.select_graph(name)

        # Initialize the backlog as disabled by default
        self.backlog = None

        # create indicies

        # index File path, name and ext fields
        try:
            self.g.create_node_range_index("File", "name", "ext")
        except Exception:
            pass

        # index Function using full-text search
        try:
            self.g.create_node_fulltext_index("Searchable", "name")
        except Exception:
            pass

    def clone(self, clone: str) -> "Graph":
        """
        Create a copy of the graph under the name clone

        Returns:
            a new instance of Graph
        """

        # Make sure key clone isn't already exists
        if self.db.connection.exists(clone):
            raise Exception(f"Can not create clone, key: {clone} already exists.")

        self.g.copy(clone)

        # Wait for the clone to become available
        while not self.db.connection.exists(clone):
            # TODO: add a waiting limit
            time.sleep(1)

        return Graph(clone)


    def delete(self) -> None:
        """
        Delete graph
        """
        self.g.delete()

    def enable_backlog(self) -> None:
        """
        Enables the backlog by initializing an empty list.
        """

        self.backlog = {'queries': [], 'params': []}
        logging.debug("Backlog enabled")

    def disable_backlog(self) -> None:
        """
        Disables the backlog by setting it to None.
        """

        self.backlog = None
        logging.debug("Backlog disabled")

    def clear_backlog(self) -> tuple[list[str], list[dict]]:
        """
        Clears and returns the backlog of queries and parameters.

        Returns:
            tuple[list[str], list[dict]]: A tuple containing two lists:
            - The first list contains the backlog of queries.
            - The second list contains the backlog of query parameters.
        """

        res = [], []  # Default return value

        if self.backlog:
            params  = self.backlog['params']
            queries = self.backlog['queries']

            # Clear backlog
            self.backlog = {'queries': [], 'params': []}

            logging.debug(f"Backlog queries: {queries}")
            logging.debug(f"Backlog params: {params}")

            # Set return value
            res = queries, params

        logging.debug("Backlog cleared")

        return res


    def _query(self, q: str, params: Optional[dict] = None) -> QueryResult:
        """
        Executes a query on the graph database and logs changes to the backlog if any.

        Args:
            q (str): The query string to execute.
            params (dict): The parameters for the query.

        Returns:
            QueryResult: The result of the query execution.
        """

        result_set = self.g.query(q, params)

        if self.backlog is not None:
            # Check if any change occurred in the query results
            change_detected = any(
                getattr(result_set, attr) > 0
                for attr in [
                    'relationships_deleted', 'nodes_deleted', 'labels_added',
                    'labels_removed', 'nodes_created', 'properties_set',
                    'properties_removed', 'relationships_created'
                ]
            )
            logging.info(f"change_detected: {change_detected}")

            # Append the query and parameters to the backlog if changes occurred
            if change_detected:
                logging.debug(f"logging queries: {q}")
                logging.debug(f"logging params: {params}")
                self.backlog['queries'].append(q)
                self.backlog['params'].append(params)

        return result_set

    def get_sub_graph(self, l: int) -> dict:

        q = """MATCH (src)
                   OPTIONAL MATCH (src)-[e]->(dest)
                   RETURN src, e, dest
                   LIMIT $limit"""

        sub_graph = {'nodes': [], 'edges': [] }

        result_set = self._query(q, {'limit': l}).result_set
        for row in result_set:
            src  = row[0]
            e    = row[1]
            dest = row[2]

            sub_graph['nodes'].append(encode_node(src))

            if e is not None:
                sub_graph['edges'].append(encode_edge(e))
                sub_graph['nodes'].append(encode_node(dest))

        return sub_graph


    def get_neighbors(self, node_ids: list[int], rel: Optional[str] = None, lbl: Optional[str] = None) -> dict[str, list[dict]]:
        """
        Fetch the neighbors of a given nodes in the graph based on relationship type and/or label.

        Args:
            node_ids (List[int]): The IDs of the source nodes.
            rel (str, optional): The type of relationship to filter by. Defaults to None.
            lbl (str, optional): The label of the destination node to filter by. Defaults to None.

        Returns:
            dict: A dictionary with lists of 'nodes' and 'edges' for the neighbors.
        """

        # Validate inputs
        if not all(isinstance(node_id, int) for node_id in node_ids):
            raise ValueError("node_ids must be an integer list")

        # Build relationship and label query parts
        rel_query = f":{rel}" if rel else ""
        lbl_query = f":{lbl}" if lbl else ""

        # Parameterized Cypher query to find neighbors
        query = f"""
            MATCH (n)-[e{rel_query}]->(dest{lbl_query})
            WHERE ID(n) IN $node_ids
            RETURN e, dest
        """

        # Initialize the neighbors structure
        neighbors = {'nodes': [], 'edges': []}

        try:
            # Execute the graph query with node_id parameter
            result_set = self._query(query, {'node_ids': node_ids}).result_set

            # Iterate over the result set and process nodes and edges
            for edge, destination_node in result_set:
                neighbors['nodes'].append(encode_node(destination_node))
                neighbors['edges'].append(encode_edge(edge))

            return neighbors

        except Exception as e:
            logging.error(f"Error fetching neighbors for node {node_ids}: {e}")
            return {'nodes': [], 'edges': []}


    def _class_from_node(self, n: Node) -> Class:
        """
        Create a Class from a graph node
        """

        doc       = n.properties.get('doc')
        name      = n.properties.get('name')
        path      = n.properties.get('path')
        src_end   = n.properties.get('src_end')
        src_start = n.properties.get('src_start')

        c = Class(path, name, doc, src_start, src_end)
        c.id = n.id

        return c

    def add_class(self, c: Class) -> None:
        """
        Adds a class node to the graph database.

        Args:
            c (Class): The Class object to be added.
        """

        q = """MERGE (c:Class:Searchable {name: $name, path: $path, src_start: $src_start,
                               src_end: $src_end})
               SET c.doc = $doc
               RETURN c"""

        params = {
            'doc': c.doc,
            'name': c.name,
            'path': c.path,
            'src_start': c.src_start,
            'src_end': c.src_end,
        }

        res  = self._query(q, params)
        node = res.result_set[0][0]
        c.id = node.id

    def get_class_by_name(self, class_name: str) -> Optional[Class]:
        q = "MATCH (c:Class) WHERE c.name = $name RETURN c LIMIT 1"
        res = self._query(q, {'name': class_name}).result_set

        if len(res) == 0:
            return None

        return self._class_from_node(res[0][0])

    def get_class(self, class_id: int) -> Optional[Class]:
        q = """MATCH (c:Class)
               WHERE ID(c) = $class_id
               RETURN c"""
        
        res = self._query(q, {'class_id': class_id})

        if len(res.result_set) == 0:
            return None

        c = res.result_set[0][0]
        return self._class_from_node(c)

    def _function_from_node(self, n: Node) -> Function:
        """
        Create a Function from a graph node
        """

        src       = n.properties.get('src')
        doc       = n.properties.get('doc')
        path      = n.properties.get('path')
        name      = n.properties.get('name')
        args      = n.properties.get('args')
        src_end   = n.properties.get('src_end')
        ret_type  = n.properties.get('ret_type')
        src_start = n.properties.get('src_start')

        f = Function(path, name, doc, ret_type, src, src_start, src_end)
        for arg in args:
            name  = arg[0]
            type_ = arg[1]
            f.add_argument(name, type_)

        f.id = n.id

        return f

    def add_function(self, func: Function) -> None:
        """
        Adds a function node to the graph database.

        Args:
            func (Function): The Function object to be added.
        """

        q = """MERGE (f:Function:Searchable {path: $path, name: $name,
                                  src_start: $src_start, src_end: $src_end})
               SET f.args = $args, f.ret_type = $ret_type, f.src = $src, f.doc = $doc
               RETURN f"""

        # Prepare arguments in a more straightforward manner
        args = [[arg.name, arg.type] for arg in func.args]
        params = {
            'src': func.src,
            'doc': func.doc,
            'path': func.path,
            'name': func.name,
            'src_start': func.src_start,
            'src_end': func.src_end,
            'args': args,
            'ret_type': func.ret_type
        }

        res     = self._query(q, params)
        node    = res.result_set[0][0]
        func.id = node.id

    # set functions metadata
    def set_functions_metadata(self, ids: list[int], metadata: list[dict]) -> None:
        assert(len(ids) == len(metadata))

        # TODO: Match (f:Function)
        q = """UNWIND range(0, size($ids)) as i
               WITH $ids[i] AS id, $values[i] AS v
               MATCH (f)
               WHERE ID(f) = id
               SET f += v
               RETURN f"""
        
        params = {'ids': ids, 'values': metadata}

        self._query(q, params)

    # get all functions defined by file
    def get_functions_in_file(self, path: str, name: str, ext: str) -> list[Function]:
        q = """MATCH (f:File {path: $path, name: $name, ext: $ext})
               MATCH (f)-[:DEFINES]->(func:Function)
               RETURN collect(func)"""

        params = {'path': path, 'name': name, 'ext': ext}
        funcs = self._query(q, params).result_set[0][0]
        
        return [self._function_from_node(n) for n in funcs]

    def get_function_by_name(self, name: str) -> Optional[Function]:
        q = "MATCH (f:Function) WHERE f.name = $name RETURN f LIMIT 1"
        res = self._query(q, {'name': name}).result_set

        if len(res) == 0:
            return None

        return self._function_from_node(res[0][0])

    def prefix_search(self, prefix: str) -> str:
        """
        Search for entities by prefix using a full-text search on the graph.
        The search is limited to 10 nodes. Each node's name and labels are retrieved,
        and the results are sorted based on their labels.

        Args:
            prefix (str): The prefix string to search for in the graph database.

        Returns:
            str: A list of entity names and corresponding labels, sorted by label.
                 If no results are found or an error occurs, an empty list is returned.
        """

        # Append a wildcard '*' to the prefix for full-text search.
        search_prefix = f"{prefix}*"

        # Cypher query to perform full-text search and limit the result to 10 nodes.
        # The 'CALL db.idx.fulltext.queryNodes' method searches for nodes labeled 'Searchable'
        # that match the given prefix, collects the nodes, and returns the result.
        query = """
            CALL db.idx.fulltext.queryNodes('Searchable', $prefix)
            YIELD node
            WITH node
            RETURN node
            LIMIT 10
        """

        # Execute the query using the provided graph database connection.
        result_set = self._query(query, {'prefix': search_prefix}).result_set

        completions = [encode_node(row[0]) for row in result_set]

        return completions


    def get_function(self, func_id: int) -> Optional[Function]:
        q = """MATCH (f:Function)
               WHERE ID(f) = $func_id
               RETURN f"""
        
        res = self._query(q, {'func_id': func_id})

        if len(res.result_set) == 0:
            return None

        node = res.result_set[0][0]

        return self._function_from_node(node)

    def function_calls(self, func_id: int) -> list[Function]:
        q = """MATCH (f:Function)
               WHERE ID(f) = $func_id
               MATCH (f)-[:CALLS]->(callee)
               RETURN callee"""

        res = self._query(q, {'func_id': func_id})

        callees = []
        for row in res.result_set:
            callee = row[0]
            callees.append(self._function_from_node(callee))

        return callees
    
    def function_called_by(self, func_id: int) -> list[Function]:
        q = """MATCH (f:Function)
               WHERE ID(f) = $func_id
               MATCH (caller)-[:CALLS]->(f)
               RETURN caller"""

        res = self._query(q, {'func_id': func_id})

        callers = []
        for row in res.result_set:
            caller = row[0]
            callers.append(self._function_from_node(caller))

        return callers

    def add_file(self, file: File) -> None:
        """
        Add a file node to the graph database.

        Args:
            file (File): The file.
        """

        q = """MERGE (f:File:Searchable {path: $path, name: $name, ext: $ext})
               RETURN f"""
        params = {'path': str(file.path), 'name': file.path.name, 'ext': file.path.suffix}

        res     = self._query(q, params)
        node    = res.result_set[0][0]
        file.id = node.id

    def delete_files(self, files: list[dict]) -> tuple[str, dict, list[int]]:
        """
        Deletes file(s) from the graph in addition to any other entity
        defined in the file

        a file is defined by its path, name and extension
        files = [{'path':_, 'name': _, 'ext': _}, ...]
        """

        q = """UNWIND $files AS file
               MATCH (f:File {path: file['path'], name: file['name'], ext: file['ext']})
               WITH collect(f) AS Fs
               UNWIND Fs AS f
               OPTIONAL MATCH (f)-[:DEFINES]->(e)
               WITH Fs, collect(e) AS Es
               WITH Fs + Es AS entities
               UNWIND entities AS e
               DELETE e
               RETURN collect(ID(e))
        """

        params = {'files': files}
        res = self._query(q, params)

        return None

    def get_file(self, path: str, name: str, ext: str) -> Optional[File]:
        """
        Retrieves a File entity from the graph database based on its path, name, and extension.

        Args:
            path (str): The file path.
            name (str): The file name.
            ext (str): The file extension.

        Returns:
            Optional[File]: The File object if found, otherwise None.

        This method constructs and executes a query to find a file node in the graph
        database with the specified path, name, and extension. If the file node is found,
        it creates and returns a File object with its properties and ID. If no such node
        is found, it returns None.

        Example:
            file = self.get_file('/path/to/file', 'filename', '.py')
        """

        q = """MATCH (f:File {path: $path, name: $name, ext: $ext})
               RETURN f"""
        params = {'path': path, 'name': name, 'ext': ext}

        res = self._query(q, params)
        if(len(res.result_set) == 0):
            return None

        node = res.result_set[0][0]

        ext  = node.properties['ext']
        path = node.properties['path']
        name = node.properties['name']
        file = File(path, name, ext)

        file.id = node.id

        return file

    # set file code coverage
    # if file coverage is 100% set every defined function coverage to 100% aswell
    def set_file_coverage(self, path: str, name: str, ext: str, coverage: float) -> None:
        q = """MATCH (f:File {path: $path, name: $name, ext: $ext})
               SET f.coverage_precentage = $coverage
               WITH f
               WHERE $coverage = 1.0
               MATCH (f)-[:DEFINES]->(func:Function)
               SET func.coverage_precentage = 1.0"""

        params = {'path': path, 'name': name, 'ext': ext, 'coverage': coverage}

        res = self._query(q, params)

    def connect_entities(self, relation: str, src_id: int, dest_id: int) -> None:
        """
        Establish a relationship between src and dest

        Args:
            src_id (int): ID of the source node.
            dest_id (int): ID of the destination node.
        """

        q = f"""MATCH (src), (dest)
                WHERE ID(src) = $src_id AND ID(dest) = $dest_id
                MERGE (src)-[e:{relation}]->(dest)
                RETURN e"""

        params = {'src_id': src_id, 'dest_id': dest_id}
        self._query(q, params)

    def function_calls_function(self, caller_id: int, callee_id: int, pos: int) -> None:
        """
        Establish a 'CALLS' relationship between two function nodes.

        Args:
            caller_id (int): ID of the caller function node.
            callee_id (int): ID of the callee function node.
            pos (int): line number on which the function call is made.
        """

        q = """MATCH (caller:Function), (callee:Function)
               WHERE ID(caller) = $caller_id AND ID(callee) = $callee_id
               MERGE (caller)-[e:CALLS {pos:$pos}]->(callee)
               RETURN e"""

        params = {'caller_id': caller_id, 'callee_id': callee_id, 'pos': pos}
        self._query(q, params)

    def _struct_from_node(self, n: Node) -> Struct:
        """
        Create a Struct from a graph node
        """

        doc       = n.properties.get('doc')
        name      = n.properties.get('name')
        path      = n.properties.get('path')
        src_end   = n.properties.get('src_end')
        src_start = n.properties.get('src_start')
        fields    = n.properties.get('fields')

        s = Struct(path, name, doc, src_start, src_end)

        # Populate struct fields
        if fields is not None:
            for field in fields:
                field_name = field[0]
                field_type = field[1]
                s.add_field(field_name, field_type)

        s.id = n.id

        return s

    def add_struct(self, s: Struct) -> None:
        """
        Adds a struct node to the graph database.

        Args:
            s (Struct): The Struct object to be added.
        """

        q = """MERGE (s:Struct:Searchable {name: $name, path: $path, src_start: $src_start,
                               src_end: $src_end})
               SET s.doc = $doc, s.fields = $fields
               RETURN s"""

        params = {
            'doc': s.doc,
            'name': s.name,
            'path': s.path,
            'src_start': s.src_start,
            'src_end': s.src_end,
            'fields': s.fields
        }

        res = self._query(q, params)
        node = res.result_set[0][0]
        s.id = node.id

    def get_struct_by_name(self, struct_name: str) -> Optional[Struct]:
        q = "MATCH (s:Struct) WHERE s.name = $name RETURN s LIMIT 1"
        res = self._query(q, {'name': struct_name}).result_set

        if len(res) == 0:
            return None

        return self._struct_from_node(res[0][0])

    def get_struct(self, struct_id: int) -> Optional[Struct]:
        q = """MATCH (s:Struct)
               WHERE ID(s) = $struct_id
               RETURN s"""
        
        res = self._query(q, {'struct_id': struct_id})

        if len(res.result_set) == 0:
            return None

        s = res.result_set[0][0]
        return self._struct_from_node(s)

    def rerun_query(self, q: str, params: dict) -> QueryResult:
        """
            Re-run a query to transition the graph from one state to another
        """

        return self._query(q, params)

    def find_paths(self, src: int, dest: int) -> list[Path]:
        """
        Find all paths between the source (src) and destination (dest) nodes.

        Args:
            src (int): The ID of the source node.
            dest (int): The ID of the destination node.

        Returns:
            List[Optional[Path]]: A list of paths found between the src and dest nodes.
            Returns an empty list if no paths are found.

        Raises:
            Exception: If the query fails or the graph database returns an error.
        """

        # Define the query to match paths between src and dest nodes.
        q = """MATCH (src), (dest)
               WHERE ID(src) = $src_id AND ID(dest) = $dest_id
               WITH src, dest
               MATCH p = (src)-[:CALLS*]->(dest)
               RETURN p
           """

        # Perform the query with the source and destination node IDs.
        result_set = self._query(q, {'src_id': src, 'dest_id': dest}).result_set

        paths = []

        # Extract paths from the query result set.
        for row in result_set:
            path  = []
            p     = row[0]
            nodes = p.nodes()
            edges = p.edges()

            for n, e in zip(nodes, edges):
                path.append(encode_node(n))
                path.append(encode_edge(e))

            # encode last node on path
            path.append(encode_node(nodes[-1]))
            paths.append(path)

        return paths

    def stats(self) -> dict:
        """
        Retrieve statistics about the graph, including the number of nodes and edges.

        Returns:
            dict: A dictionary containing:
                - 'node_count' (int): The total number of nodes in the graph.
                - 'edge_count' (int): The total number of edges in the graph.
        """

        q = "MATCH (n) RETURN count(n)"
        node_count = self._query(q).result_set[0][0]

        q = "MATCH ()-[e]->() RETURN count(e)"
        edge_count = self._query(q).result_set[0][0]

        # Return the statistics
        return {'node_count': node_count, 'edge_count': edge_count}

    def unreachable_entities(self, lbl: Optional[str], rel: Optional[str]) -> list[dict]:
        lbl = f": {lbl}" if lbl else ""
        rel = f": {rel}" if rel else ""

        q = f""" MATCH (n {lbl})
                 WHERE not ()-[{rel}]->(n)
                 RETURN n
        """

        result_set = self._query(q).result_set

        unreachables = []
        for row in result_set:
            node = row[0]
            unreachables.append(encode_node(node))

        return unreachables

