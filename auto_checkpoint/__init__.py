import os
import sys
import json
import fnmatch

import comfy.sd
import comfy.utils
import folder_paths

MAP_FILE = os.path.join(os.path.dirname(__file__), "model_map.json")


def norm(name):
    return name.replace("\\", "/")


def load_map():
    if not os.path.isfile(MAP_FILE):
        return {}
    with open(MAP_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {norm(k): v for k, v in data.items()}


def find_entry(mapping, ckpt_name, arch):
    name = norm(ckpt_name)
    if name in mapping:
        return name, mapping[name]
    for pattern, entry in mapping.items():
        if pattern.startswith("@"):
            continue
        if fnmatch.fnmatchcase(name, pattern):
            return pattern, entry
    arch_key = "@" + arch
    if arch_key in mapping:
        return arch_key, mapping[arch_key]
    return None, {}


def resolve(folder, name):
    path = folder_paths.get_full_path(folder, name)
    if path is None:
        path = folder_paths.get_full_path(folder, name.replace("/", "\\"))
    if path is None:
        raise FileNotFoundError(f"[AutoCheckpoint] {folder}: {name} not found")
    return path


_capture_registered = False


def register_metadata_capture():
    global _capture_registered
    if _capture_registered:
        return
    done = set()
    for modname, mod in list(sys.modules.items()):
        capture_list = getattr(mod, "CAPTURE_FIELD_LIST", None)
        if not isinstance(capture_list, dict) or id(capture_list) in done:
            continue
        meta = sys.modules.get(modname + ".meta") or sys.modules.get(modname.rsplit(".", 1)[0] + ".meta")
        if meta is None or not hasattr(meta, "MetaField"):
            continue
        base = meta.__name__.rsplit(".", 1)[0]
        formatters = sys.modules.get(base + ".formatters")
        entry = {meta.MetaField.MODEL_NAME: {"field_name": "ckpt_name"}}
        if formatters is not None and hasattr(formatters, "calc_model_hash"):
            entry[meta.MetaField.MODEL_HASH] = {"field_name": "ckpt_name", "format": formatters.calc_model_hash}
        capture_list["AutoCheckpointLoader"] = entry
        done.add(id(capture_list))
        print(f"[AutoCheckpoint] Metadata capture registered in {modname}")
    if done:
        _capture_registered = True
    else:
        print("[AutoCheckpoint] No metadata capture list found, %model% stays empty")


class AutoCheckpointLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"ckpt_name": (folder_paths.get_filename_list("checkpoints"),)}}

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "STRING")
    RETURN_NAMES = ("model", "clip", "vae", "info")
    FUNCTION = "load"
    CATEGORY = "X4Lch3mist/loaders"

    @classmethod
    def IS_CHANGED(cls, ckpt_name):
        mtime = os.path.getmtime(MAP_FILE) if os.path.isfile(MAP_FILE) else 0
        return f"{ckpt_name}-{mtime}"

    def load(self, ckpt_name):
        register_metadata_capture()
        mapping = load_map()
        emb_dir = folder_paths.get_folder_paths("embeddings")

        ckpt_path = folder_paths.get_full_path_or_raise("checkpoints", ckpt_name)
        out = comfy.sd.load_checkpoint_guess_config(ckpt_path, output_vae=True, output_clip=True, embedding_directory=emb_dir)
        model, clip, vae = out[0], out[1], out[2]

        arch = type(model.model.model_config).__name__
        matched, entry = find_entry(mapping, ckpt_name, arch)

        vae_src = "checkpoint"
        vae_name = entry.get("vae")
        if vae_name:
            sd = comfy.utils.load_torch_file(resolve("vae", vae_name))
            vae = comfy.sd.VAE(sd=sd)
            vae_src = vae_name

        clip_src = "checkpoint"
        clip_names = entry.get("clip")
        if clip_names and arch not in ("SD15", "SD20", "SDXL", "SDXLRefiner"):
            print(f"[AutoCheckpoint] External CLIP not supported for {arch}, using checkpoint CLIP")
            clip_names = None
        if clip_names:
            if isinstance(clip_names, str):
                clip_names = [clip_names]
            clip_paths = [resolve("text_encoders", c) for c in clip_names]
            clip = comfy.sd.load_clip(ckpt_paths=clip_paths, embedding_directory=emb_dir, clip_type=comfy.sd.CLIPType.STABLE_DIFFUSION)
            clip_src = ", ".join(clip_names)

        info = f"ckpt={ckpt_name} | arch={arch} | match={matched or '-'} | vae={vae_src} | clip={clip_src}"
        print(f"[AutoCheckpoint] {info}")
        return (model, clip, vae, info)

NODE_CLASS_MAPPINGS = {"AutoCheckpointLoader": AutoCheckpointLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"AutoCheckpointLoader": "Load Checkpoint (Auto VAE/CLIP)"}
