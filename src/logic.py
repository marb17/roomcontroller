"""
Logic Structure

class ClassName:
    @staticmethod
    def function_name(panel_context):
        ...
        return ...
"""

import hardware

class MainPower:
    """
    Main power switch, if not enabled, other systems cannot be activated
    """
    @staticmethod
    def is_powered(panel_context: dict) -> bool:
        """
        Requires a switch object to be passed in as panel_context["main_power"]
        """
        if type(panel_context["main_power"]) is not hardware.Switch:
            raise TypeError("Main power switch must be a Switch object!")

        if panel_context["main_power"].is_pressed:
            return True
        else:
            return False