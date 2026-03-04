import logging
import sys

logging.basicConfig(level=logging.INFO)
sys.path.append("/Code/grokbox")

from skills.skill_manager import SkillManager
s = SkillManager()
print(f"Loaded tools: {len(s.get_tool_schemas())}")
