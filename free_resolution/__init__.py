import math
import torch


class FreeResolutionSelector:
    """
    Like the built-in ResolutionSelector, but with a freely configurable
    aspect ratio (two numeric fields) instead of a fixed dropdown. 
    Outputs a 16-channel latent at 8x downscale.
    """

    CATEGORY = "X4Lch3mist/latent"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "megapixel": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 16.0, "step": 0.1}),
                "multiple": ("INT", {"default": 8, "min": 8, "max": 128, "step": 8}),
                "ratio_width": ("INT", {"default": 16, "min": 1, "max": 1000, "step": 1}),
                "ratio_height": ("INT", {"default": 10, "min": 1, "max": 1000, "step": 1}),
            }
        }

    RETURN_TYPES = ("LATENT", "INT", "INT")
    RETURN_NAMES = ("LATENT", "width", "height")
    FUNCTION = "generate"

    @staticmethod
    def _round_to_multiple(x: float, multiple: int) -> int:
        return max(multiple, int(round(x / multiple) * multiple))

    def generate(self, megapixel, multiple, ratio_width, ratio_height):
        target_area = megapixel * 1_000_000
        scale = math.sqrt(target_area / (ratio_width * ratio_height))

        width = self._round_to_multiple(ratio_width * scale, multiple)
        height = self._round_to_multiple(ratio_height * scale, multiple)

        latent = torch.zeros([1, 16, height // 8, width // 8])
        return ({"samples": latent}, width, height)

NODE_CLASS_MAPPINGS = {"FreeResolutionSelector": FreeResolutionSelector}
NODE_DISPLAY_NAME_MAPPINGS = {"FreeResolutionSelector": "Free Resolution Selector (custom ratio)"}
