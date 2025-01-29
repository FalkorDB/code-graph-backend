from typing import Union
from tree_sitter import Node

def print_node(node, indent=0):
    """
    Recursively print a tree-sitter node and its children.

    Args:
        node: The tree-sitter node to print.
        indent: The current indentation level for pretty printing.
    """
    indent_str = '  ' * indent
    print(f"{indent_str}{node.type}")

    for child in node.children:
        print_node(child, indent + 1)

def find_child_of_type(node: Node, child_type: str) -> Union[tuple[Node, int], None]:
    for idx, child in enumerate(node.children):
        if child.type == child_type:
            return (child, idx)

    return None

def extract_js_function_name(node: Node) -> str:
    """
    Extract the function name from a JavaScript function node.

    Args:
        node (Node): The AST node representing the function.

    Returns:
        str: The name of the function.
    """
    for child in node.children:
        if child.type == 'identifier':
            return child.text.decode('utf-8')
    return ''

def extract_js_class_name(node: Node) -> str:
    """
    Extract the class name from a JavaScript class node.

    Args:
        node (Node): The AST node representing the class.

    Returns:
        str: The name of the class.
    """
    for child in node.children:
        if child.type == 'identifier':
            return child.text.decode('utf-8')
    return ''
