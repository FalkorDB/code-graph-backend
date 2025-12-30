import unittest
from pathlib import Path

from api import SourceAnalyzer, Graph

class Test_Kotlin_Analyzer(unittest.TestCase):
    def test_analyzer(self):
        analyzer = SourceAnalyzer()

        # Get the path to the test Kotlin source files
        path = str(Path(__file__).parent / 'source_files' / 'kotlin')

        g = Graph("kotlin")
        analyzer.analyze_local_folder(path, g)

        # Test that files were parsed
        self.assertGreater(len(g.entities), 0)
        
        print(f"Entities found: {len(g.entities)}")
        for entity_id, entity_data in g.entities.items():
            print(f"  - {entity_data.get('label')}: {entity_data.get('name')}")

if __name__ == '__main__':
    unittest.main()
