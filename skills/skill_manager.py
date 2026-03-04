import os
import glob
import importlib
import inspect
import json
import logging

log = logging.getLogger("grokbox.skills")

class SkillManager:
    def __init__(self, skills_dir="/Code/grokbox/skills"):
        self.skills_dir = skills_dir
        self.tools = []
        self.functions = {}
        self.load_skills()

    def load_skills(self):
        # Add the parent of skills dir to path so we can import 'skills.x'
        parent_dir = os.path.dirname(self.skills_dir)
        import sys
        if parent_dir not in sys.path:
            sys.path.append(parent_dir)

        skill_files = glob.glob(os.path.join(self.skills_dir, "*.py"))
        
        for file in skill_files:
            basename = os.path.basename(file)
            if basename.startswith("_") or basename == "skill_manager.py":
                continue
                
            module_name = f"skills.{basename[:-3]}"
            try:
                module = importlib.import_module(module_name)
                # Look for a TOOL_SCHEMA list and exported functions
                if hasattr(module, "TOOL_SCHEMAS"):
                    for schema in module.TOOL_SCHEMAS:
                        func_name = schema["function"]["name"]
                        if hasattr(module, func_name):
                            self.tools.append(schema)
                            self.functions[func_name] = getattr(module, func_name)
                            log.info(f"Loaded skill: {func_name}")
                        else:
                            log.error(f"Skill module {module_name} defines schema for {func_name} but missing implementation.")
            except Exception as e:
                log.error(f"Failed to load skill {module_name}: {e}")

    def get_tool_schemas(self):
        return self.tools

    def execute_tool(self, tool_call):
        """
        Executes the requested tool call and returns the response string.
        """
        fn_name = tool_call.get("function", {}).get("name")
        args_str = tool_call.get("function", {}).get("arguments", "{}")
        
        log.info(f"Executing tool: {fn_name} with args: {args_str}")

        if fn_name not in self.functions:
            return f"Error: Function {fn_name} not found."

        try:
            args = json.loads(args_str)
            result = self.functions[fn_name](**args)
            return str(result)
        except Exception as e:
            log.error(f"Error executing {fn_name}: {e}")
            return f"Error executing tool: {e}"
