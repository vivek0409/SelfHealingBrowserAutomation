import os
import sys
import unittest
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.schema import FlowSchema, FlowStep, RunReport, RunArtifacts
from core import storage
from agents import regression_monitor, execution_agent

class TestBrowserAutomationAgent(unittest.TestCase):
    
    def setUp(self):
        # Database should already be initialized on import
        pass
        
    def test_database_serialization(self):
        # Verify db flow operations
        steps = [
            FlowStep(step_id=1, action="navigate", value="https://example.com"),
            FlowStep(step_id=2, action="click", selector="button.submit", description="Submit login form")
        ]
        flow = FlowSchema(
            flow_id="test-flow-id-123",
            flow_name="Login Test Scenario",
            url="https://example.com",
            steps=steps,
            created_at=datetime.utcnow().isoformat() + "Z",
            target_framework="playwright"
        )
        
        # Save flow
        storage.save_flow(flow)
        
        # Load flow and verify
        loaded = storage.get_flow("test-flow-id-123")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.flow_name, "Login Test Scenario")
        self.assertEqual(len(loaded.steps), 2)
        self.assertEqual(loaded.steps[1].selector, "button.submit")

    def test_regression_monitor_identical(self):
        # Test visual diff on same images (mocked paths)
        # Create tiny mock black images
        from PIL import Image
        
        mock_baseline = os.path.join(os.path.dirname(__file__), "mock_baseline.png")
        mock_current = os.path.join(os.path.dirname(__file__), "mock_current.png")
        diff_dir = os.path.join(os.path.dirname(__file__), "diff_out")
        
        os.makedirs(os.path.dirname(mock_baseline), exist_ok=True)
        
        img = Image.new("RGB", (100, 100), color="black")
        img.save(mock_baseline)
        img.save(mock_current)
        
        try:
            report = regression_monitor.compare_screenshots(mock_baseline, mock_current, diff_dir)
            self.assertEqual(report["diff_percentage"], 0.0)
            self.assertEqual(report["status"], "pass")
        finally:
            if os.path.exists(mock_baseline): os.remove(mock_baseline)
            if os.path.exists(mock_current): os.remove(mock_current)
            if os.path.exists(os.path.join(diff_dir, "visual_diff.png")):
                os.remove(os.path.join(diff_dir, "visual_diff.png"))
                
if __name__ == "__main__":
    unittest.main()
