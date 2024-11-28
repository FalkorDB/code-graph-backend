import io
import os
from ..utils import *
from pathlib import Path
from ...entities import *
from ...graph import Graph
from typing import Union, Optional
from ..analyzer import AbstractAnalyzer

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

PY_LANGUAGE = Language(tspython.language())

import logging
logger = logging.getLogger('code_graph')

class PythonAnalyzer(AbstractAnalyzer):
    def __init__(self) -> None:
        self.parser = Parser(PY_LANGUAGE)

    def process_class_definition(self, node: Node, path: Path) -> tuple[Class, list[str]]:
        """
        Processes a class definition node from the syntax tree and extracts relevant information.

        Args:
            node (Node): The Tree-sitter node representing the class definition.
            path (Path): The file path where the class is defined.

        Returns:
            Class: An instance of the Class containing the extracted information.

        This function performs the following tasks:
            1. Extracts the class name from the node.
            2. Extracts the docstring if it exists.
            3. Extracts the list of inherited classes.
            4. Creates a Class object with the extracted information.

        Example:
            Given a Tree-sitter node representing a class definition, this function will extract
            the class name, docstring, and inherited classes, and create a corresponding Class
            object, which will then be added to the graph.

        Note:
            This function assumes that the Tree-sitter node structure follows a specific pattern
            for class definitions in Python.
        """

        # Extract class name
        class_name = node.child_by_field_name("name")
        class_name = class_name.text.decode("utf8")
        logger.info(f"Class declaration: {class_name}")

        # Extract docstring
        docstring_node = None
        body_node = node.child_by_field_name('body')
        if body_node.child_count > 0 and body_node.child(0).type == 'expression_statement':
            docstring_node = body_node.child(0).child(0)

        docstring = docstring_node.text.decode('utf-8') if docstring_node else None
        logger.debug(f"Class docstring: {docstring}")

        # Extract inherited classes
        inherited_classes_node = node.child_by_field_name('superclasses')
        inherited_classes = []
        if inherited_classes_node:
            for child in inherited_classes_node.children:
                if child.type == 'identifier':
                    inherited_classes.append(child.text.decode('utf-8'))
        logger.debug(f"Class inherited classes: {inherited_classes}")

        # Create Class object
        c = Class(str(path), class_name, docstring,
                   node.start_point[0], node.end_point[0])

        return (c, inherited_classes)

    def process_function_definition(self, node: Node, path: Path, source_code: str) -> Function:
        """
        Processes a function definition node from the syntax tree and extracts relevant information.

        Args:
            node (Node): The Tree-sitter node representing the function definition.
            path (Path): The file path where the function is defined.

        Returns:
            Function: An instance of the Function class containing the extracted information.

        This function performs the following tasks:
            1. Extracts the function name.
            2. Extracts the function body, parameters, return type, docstring, and line numbers.
            3. Creates a Function object with the extracted information and adds arguments.

        Example:
            Given a Tree-sitter node representing a function definition, this function will extract
            the function name, docstring, arguments with their types, return type, and source line
            numbers. It then creates a Function object, adds the arguments, and finally adds the
            Function object to the graph.

        Note:
            This function assumes that the Tree-sitter node structure follows a specific pattern
            for function definitions in Python.
        """

        # Extract function name
        function_name = node.child_by_field_name('name').text.decode('utf-8')
        logger.info(f"Function declaration: {function_name}")

        # Extract function body, parameters, return type
        body = node.child_by_field_name('body')
        parameters = node.child_by_field_name('parameters')
        return_type = node.child_by_field_name('return_type')

        # Extract function definition line numbers
        start_line = node.start_point[0]
        end_line = node.end_point[0]

        # Extract docstring
        docstring = None
        if body and body.child_count > 0 and body.children[0].type == 'expression_statement':
            first_child = body.children[0]
            if first_child.child(0).type == 'string':
                docstring = first_child.child(0).text.decode('utf-8')

        # Extract arguments and their types
        args = []
        if parameters:
            for param in parameters.children:
                if param.type == 'identifier':
                    arg_name = param.text.decode('utf-8')
                    arg_type = None
                    if param.next_sibling and param.next_sibling.type == 'type':
                        arg_type = param.next_sibling.text.decode('utf-8')
                elif param.type == 'typed_parameter':
                    arg_name_node = param.children[0]
                    arg_type_node = param.children[2].children[0]

                    arg_name = arg_name_node.text.decode('utf-8')
                    arg_type = arg_type_node.text.decode('utf-8')
                elif param.type == 'typed_default_parameter':
                    arg_name_node = param.children[0]
                    arg_type_node = param.children[2].children[0]

                    arg_name = arg_name_node.text.decode('utf-8')
                    arg_type = arg_type_node.text.decode('utf-8')

                else:
                    logger.debug(f'Unknown function parameter node type: {param.type}')
                    continue

                args.append((arg_name, arg_type))

        # Extract return type
        ret_type = return_type.text.decode('utf-8') if return_type else None

        # Create Function object
        src = source_code[node.start_byte:node.end_byte]
        f = Function(str(path), function_name, docstring, ret_type, src, start_line, end_line)

        # Add arguments to Function object
        for arg in args:
            f.add_argument(arg[0], arg[1])

        return f

    def first_pass_traverse(self, parent: Union[File,Class,Function], node: Node,
                            path: Path, graph: Graph, source_code: str) -> None:
        """
        Recursively traverses a syntax tree node, processes class and function definitions,
        and connects them in a graph representation.

        Args:
            parent (Union[File, Class, Function]): The parent entity (File, Class, or Function) to connect to.
            node (Node): The Tree-sitter node to process.
            path (Path): The path of the file being analyzed.

        This method processes each node based on its type:
            - If the node represents a class definition ('class_definition'), it invokes
              'process_class_definition' to extract class information and connects it to the parent entity.
            - If the node represents a function definition ('function_definition'), it invokes
              'process_function_definition' to extract function information and connects it to the parent entity.
            - Recursively visits child nodes to continue the traversal.

        Note:
            The method assumes that the Tree-sitter node structure follows a specific pattern
            for class and function definitions in Python.

        Example:
            Given a Tree-sitter node representing a Python file's syntax tree, this method
            recursively traverses each node, processes class and function definitions,
            connects them in a graph representation, and updates the parent entity accordingly.
        """

        entity = None

        if node.type == "class_definition":
            entity = self.process_class_definition(node, path)[0]
            # Add Class object to the graph
            graph.add_class(entity)

        elif node.type == "function_definition":
            entity = self.process_function_definition(node, path, source_code)
            # Add Function object to the graph
            graph.add_function(entity)

        if entity is not None:
            # Connect parent to entity and update parent
            graph.connect_entities('DEFINES', parent.id, entity.id)
            parent = entity

        # Recursivly visit child nodes
        for child in node.children:
            self.first_pass_traverse(parent, child, path, graph, source_code)

    def first_pass(self, path: Path, f: io.TextIOWrapper, graph:Graph) -> None:
        """
        Perform the first pass of analysis on the given file.

        Args:
            path (Path): The path to the file being processed.
            f (io.TextIOWrapper): The file object.
        """

        if path.suffix != '.py':
            logger.debug("Skipping none Python file %s", path)
            return

        logger.info("Python Processing %s", path)

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

        # Walk thought the AST
        self.first_pass_traverse(file, tree.root_node, path, graph, source_code)

    def process_function_call(self, node) -> Optional[str]:
        """
        Process a function call node to extract the callee's name.

        Args:
            node (Node): The function call node in the AST.

        Returns:
            Optional[str]: The name of the callee function or None if it cannot be determined.
        """

        # locate argument_list node
        res = find_child_of_type(node, 'argument_list')
        if res is None:
            logger.warning("Failed to locate 'argument_list'")
            return None

        callee_name = None
        argument_list, idx = res
        sibling = node.children[idx-1]

        # Determine the type of the sibling node and extract the callee's name
        if sibling.type == 'identifier':
            callee_name = sibling.text.decode('utf-8')
        elif sibling.type == 'attribute':
            # call
              # attribute (sibling)
                # identifier
                # .
                # identifier
              # argument_list
            idx = len(sibling.children)-1
            callee_name = sibling.children[idx].text.decode('utf-8')
        else:
            # Add support additional call constructs
            logger.warning("Unknown function call pattern")
            return None

        logger.debug("callee_name: %s", callee_name)
        return callee_name

    def process_call_node(self, caller: Union[Function, File], callee_name: str,
                          graph:Graph) -> None:
        """
        Process a call node in the AST, connecting the caller to the callee in the graph.

        Args:
            caller (Union[Function, File]): The caller entity in the graph.
            callee_name (str): The name of the callee function or class.
        """

        # Attempt to find the callee as a function first
        callee = graph.get_function_by_name(callee_name)

        # If the callee is not a function, check if it is a class
        if callee is None:
            callee = graph.get_class_by_name(callee_name)

            # If the callee is neither a function nor a class, create a new function entity
            if callee is None:
                # Create Function callee_name
                # Assuming this is a call to either a native or imported Function
                # Although this call might just be a Class instantiation.
                logger.info(f"Creating missing Class/Function {callee_name}")
                callee = Function('/', callee_name, None, None, None,0, 0)
                graph.add_function(callee)

        # Connect the caller and callee in the graph
        graph.connect_entities('CALLS', caller.id, callee.id)

    def process_inheritance(self, cls: Class, super_classes: list[str],
                            graph: Graph) -> None:
        for super_class in super_classes:
            logger.info(f"Class {cls.name} inherits {super_class}")

            # Try to get Class object from graph
            _super_class = graph.get_class_by_name(super_class)
            if _super_class is None:
                # Missing super class, might be imported from external library
                # Create missing class.
                _super_class = Class('/', super_class, '', 0, 0)
                graph.add_class(_super_class)

            # Connect class to its super class
            graph.connect_entities('INHERITS', cls.id, _super_class.id)

    def second_pass_traverse(self, parent: Union[File, Class, Function],
                             node: Node, path: Path, graph: Graph, source_code: str) -> None:
        """
        Traverse the AST nodes during the second pass and process each node accordingly.

        Args:
            parent (Union[File, Class, Function]): The parent entity in the graph.
            node (Node): The current AST node being processed.
            path (Path): The path to the file being processed.
        """

        if node.type == "class_definition":
            cls, super_classes = self.process_class_definition(node, path)
            cls = graph.get_class_by_name(cls.name)
            self.process_inheritance(cls, super_classes, graph)
            parent = cls

        elif node.type == "function_definition":
            # TODO: simply extract function name, no need to parse entire function
            # see C analyzer
            func = self.process_function_definition(node, path, source_code)
            parent = graph.get_function_by_name(func.name)
        elif node.type == "call":
            callee = self.process_function_call(node)
            if callee is not None:
                self.process_call_node(parent, callee, graph)

        # Recursivly visit child nodes
        for child in node.children:
            self.second_pass_traverse(parent, child, path, graph, source_code)

    def second_pass(self, path: Path, f: io.TextIOWrapper, graph: Graph) -> None:
        """
        Perform a second pass analysis on the given Python file.

        Args:
            path (Path): The path to the file.
            f (io.TextIOWrapper): The file handle of the file to be processed.
        """

        if path.suffix != '.py':
            logger.debug(f"Skipping none Python file {path}")
            return

        logger.info(f"Processing {path}")

        # Get file entity
        file = graph.get_file(os.path.dirname(path), path.name, path.suffix)
        if file is None:
            logger.error(f"File entity not found for: {path}")
            return

        try:
            # Parse file
            source_code = f.read()
            tree = self.parser.parse(source_code)

            # Walk thought the AST
            self.second_pass_traverse(file, tree.root_node, path, graph, source_code)
        except Exception as e:
            logger.error(f"Failed to process file {path}: {e}")
