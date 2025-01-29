import io
import os
from ..utils import *
from pathlib import Path
from ...entities import *
from ...graph import Graph
from typing import Optional
from ..analyzer import AbstractAnalyzer

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser, Node

JS_LANGUAGE = Language(tsjs.language())

import logging
logger = logging.getLogger('code_graph')

class JavaScriptAnalyzer(AbstractAnalyzer):
    def __init__(self) -> None:
        self.parser = Parser(JS_LANGUAGE)

    def process_function_declaration(self, node: Node, path: Path, source_code: str) -> Optional[Function]:
        """
        Processes a function declaration node to extract function details.

        Args:
            node (Node): The AST node representing a function declaration.
            path (Path): The file path where the function is defined.

        Returns:
            Optional[Function]: A Function object containing details about the function, or None if the function name cannot be determined.
        """

        # Extract function name
        res = find_child_of_type(node, 'identifier')
        if res is None:
            return None

        identifier = res[0]
        function_name = identifier.text.decode('utf-8')
        logger.info(f"Function declaration: {function_name}")

        # Extract function parameters
        args = []
        res = find_child_of_type(node, 'formal_parameters')
        if res is not None:
            parameters = res[0]

            # Extract arguments and their types
            for child in parameters.children:
                if child.type == 'identifier':
                    arg_name = child.text.decode('utf-8')
                    args.append((arg_name, 'Unknown'))

        # Extract function definition line numbers
        start_line = node.start_point[0]
        end_line = node.end_point[0]

        # Create Function object
        docs = ''
        src = source_code[node.start_byte:node.end_byte]
        f = Function(str(path), function_name, docs, 'Unknown', src, start_line, end_line)

        # Add arguments to Function object
        for arg in args:
            name = arg[0]
            type_ = arg[1]
            f.add_argument(name, type_)

        return f

    def process_class_declaration(self, node: Node, path: Path) -> Optional[Class]:
        """
        Processes a class declaration node to extract class details.

        Args:
            node (Node): The AST node representing a class declaration.
            path (Path): The file path where the class is defined.

        Returns:
            Optional[Class]: A Class object containing details about the class, or None if the class name cannot be determined.
        """

        # Extract class name
        res = find_child_of_type(node, 'identifier')
        if res is None:
            return None

        identifier = res[0]
        class_name = identifier.text.decode('utf-8')
        logger.info(f"Class declaration: {class_name}")

        # Extract class definition line numbers
        start_line = node.start_point[0]
        end_line = node.end_point[0]

        # Create Class object
        docs = ''
        c = Class(str(path), class_name, docs, start_line, end_line)

        return c

    def first_pass(self, path: Path, f: io.TextIOWrapper, graph: Graph) -> None:
        """
        Perform the first pass processing of a JavaScript source file.

        Args:
            path (Path): The path to the JavaScript source file.
            f (io.TextIOWrapper): The file object representing the opened JavaScript source file.
            graph (Graph): The Graph object where entities will be added.

        Returns:
            None
        """

        if path.suffix != '.js':
            logger.debug(f"Skipping none JavaScript file {path}")
            return

        logger.info(f"Processing {path}")

        # Create file entity
        file = File(os.path.dirname(path), path.name, path.suffix)
        graph.add_file(file)

        # Parse file
        source_code = f.read()
        tree = self.parser.parse(source_code)
        try:
            source_code = source_code.decode('utf-8')
        except Exception as e:
            logger.error(f"Failed decoding source code: {e}")
            source_code = ''

        # Process function declarations
        query = JS_LANGUAGE.query("(function_declaration) @function")
        captures = query.captures(tree.root_node)
        if 'function' in captures:
            functions = captures['function']
            for node in functions:
                entity = self.process_function_declaration(node, path, source_code)
                if entity is not None:
                    graph.add_function(entity)
                    graph.connect_entities('DEFINES', file.id, entity.id)

        # Process class declarations
        query = JS_LANGUAGE.query("(class_declaration) @class")
        captures = query.captures(tree.root_node)
        if 'class' in captures:
            classes = captures['class']
            for node in classes:
                entity = self.process_class_declaration(node, path)
                if entity is not None:
                    graph.add_class(entity)
                    graph.connect_entities('DEFINES', file.id, entity.id)

    def second_pass(self, path: Path, f: io.TextIOWrapper, graph: Graph) -> None:
        """
        Perform the second pass processing of a JavaScript source file to establish function call relationships.

        Args:
            path (Path): The path to the JavaScript source file.
            f (io.TextIOWrapper): The file object representing the opened JavaScript source file.
            graph (Graph): The Graph object containing entities (functions and files) to establish relationships.

        Returns:
            None
        """

        if path.suffix != '.js':
            logger.debug(f"Skipping none JavaScript file {path}")
            return

        logger.info(f"Processing {path}")

        # Get file entity
        file = graph.get_file(os.path.dirname(path), path.name, path.suffix)
        if file is None:
            logger.error(f"File entity not found for: {path}")
            return

        try:
            # Parse file
            content = f.read()
            tree = self.parser.parse(content)
        except Exception as e:
            logger.error(f"Failed to process file {path}: {e}")
            return

        # Locate function invocation
        query_call_exp = JS_LANGUAGE.query("(call_expression function: (identifier) @callee)")

        # Locate function definitions
        query_function_def = JS_LANGUAGE.query("""
            (
                function_declaration
                    declarator: (identifier) @function_name
            )""")

        function_defs = query_function_def.captures(tree.root_node)
        for function_def in function_defs:
            caller = function_def[0]
            caller_name = caller.text.decode('utf-8')
            caller_f = graph.get_function_by_name(caller_name)
            assert(caller_f is not None)

            function_calls = query_call_exp.captures(caller.parent.parent)
            for function_call in function_calls:
                callee = function_call[0]
                callee_name = callee.text.decode('utf-8')
                callee_f = graph.get_function_by_name(callee_name)

                if callee_f is None:
                    # Create missing function
                    # Assuming this is a call to a native function
                    callee_f = Function('/', callee_name, None, None, None, 0, 0)
                    graph.add_function(callee_f)

                # Connect the caller and callee in the graph
                graph.connect_entities('CALLS', caller_f.id, callee_f.id)
