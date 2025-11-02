import os
import unittest
from pathlib import Path

from api import SourceAnalyzer, Graph

class Test_Kotlin_Analyzer(unittest.TestCase):
    def test_analyzer(self):
        path = Path(__file__).parent
        analyzer = SourceAnalyzer()

        # Get the current file path
        current_file_path = os.path.abspath(__file__)

        # Get the directory of the current file
        current_dir = os.path.dirname(current_file_path)

        # Append 'source_files/kotlin' to the current directory
        path = os.path.join(current_dir, 'source_files')
        path = os.path.join(path, 'kotlin')
        path = str(path)

        g = Graph("kotlin")
        analyzer.analyze_local_folder(path, g)

        # Test that files were parsed
        self.assertGreater(len(g.entities), 0)
        
        print(f"Entities found: {len(g.entities)}")
        for entity_id, entity_data in g.entities.items():
            print(f"  - {entity_data.get('label')}: {entity_data.get('name')}")

if __name__ == '__main__':
    unittest.main()
