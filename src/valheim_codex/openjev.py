"""Native MLX readout of the trained OpenJev NLI head (no text generation).

The model is loaded from a pinned local checkpoint. This module is imported only
inside the isolated System 1 worker, not by the game gateway.
"""
import json
import time
from pathlib import Path

REPOSITORY = "AlexWortega/openjev"
REVISION = "f004f37e52695d6ddfb914a64dbf93942839ba1e"
SUBFOLDER = "qwen3.5-0.8b-nli-v2s-long"


class OpenJev:
    def __init__(self, path, image_size=(384, 216), quantize_bits=None, compute_dtype="float16", min_pixels=None):
        import mlx.core as mx
        import mlx.nn as nn
        from mlx_vlm.models.qwen3_5 import Model, ModelConfig
        from transformers import AutoTokenizer, AutoImageProcessor
        path = Path(path)
        config = json.loads((path / "config.json").read_text())
        provenance = json.loads((path / "provenance.json").read_text())
        if provenance != {"repo": REPOSITORY, "revision": REVISION, "subfolder": SUBFOLDER}:
            raise ValueError("Unreviewed System 1 checkpoint identity")
        if config.get("id2label") != {"0": "contradiction", "1": "entailment", "2": "neutral"}:
            raise ValueError("Unexpected OpenJev classifier labels")
        self.mx = mx
        self.model = Model(ModelConfig.from_dict(config))
        self.model.score = nn.Linear(config["text_config"]["hidden_size"], 3, bias=False)
        weights = mx.load(str(path / "model.safetensors"))
        if "score.weight" not in weights:
            raise ValueError("Trained OpenJev classification head missing")
        self.model.load_weights(list(self.model.sanitize(weights).items()), strict=True)
        if compute_dtype not in ("float32", "float16", "bfloat16"):
            raise ValueError("Unsupported computation precision")
        self.model.set_dtype(getattr(mx, compute_dtype))
        if quantize_bits is not None:
            if quantize_bits not in (4,8):
                raise ValueError("Unsupported quantization")
            # Keep the trained classification head AND vision tower unquantized.
            nn.quantize(self.model.language_model.model, group_size=64, bits=quantize_bits)
        self.model.eval()
        mx.eval(self.model.parameters())
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        self.tokenizer.padding_side = "right"
        self.processor = AutoImageProcessor.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        if min_pixels is not None:
            if min_pixels not in (32768,65536):
                raise ValueError("Unreviewed visual pixel budget")
            self.processor.size["shortest_edge"] = min_pixels
        self.template = config["nli_template"]
        self.image_size = image_size
        self.identity = dict(provenance, language_bits=quantize_bits or (32 if compute_dtype == "float32" else 16), compute_dtype=compute_dtype,
            image_size=list(image_size),min_pixels=self.processor.size["shortest_edge"])

    def prepare(self, premise, hypotheses, image=None):
        mx = self.mx
        if not 1 <= len(hypotheses) <= 12:
            raise ValueError("Use 1–12 bounded candidates")
        visual = None
        if image is not None:
            from PIL import Image
            if not isinstance(image, Image.Image):
                image = Image.open(image)
            image = image.convert("RGB")
            image.thumbnail(self.image_size)
            processed = self.processor(images=[image], return_tensors="np")
            grid = processed["image_grid_thw"]
            count = int(grid.prod()) // self.processor.merge_size ** 2
            marker = "<|vision_start|>" + "<|image_pad|>" * count + "<|vision_end|>"
            premise = marker + " " + premise
            visual = (mx.array(processed["pixel_values"]), mx.array(grid))
        texts = [self.template.format(premise=premise.strip(), hypothesis=h.strip()) for h in hypotheses]
        enc = self.tokenizer(texts, padding=True, return_tensors="np", add_special_tokens=False)
        if enc["input_ids"].shape[1] > 1024:
            raise ValueError("System 1 context exceeds its latency budget")
        return {"ids": mx.array(enc["input_ids"]), "lengths": mx.array(enc["attention_mask"].sum(-1)),
                "mask": mx.array(enc["attention_mask"]), "visual": visual, "texts": texts,
                "numpy_ids": enc["input_ids"], "numpy_mask": enc["attention_mask"]}

    def score(self, premise, hypotheses, image=None, share_prefix=True):
        mx = self.mx
        started = time.monotonic()
        data = self.prepare(premise, hypotheses, image)
        prepared_at = time.monotonic()
        ids = data["ids"]
        if data["visual"] is None:
            embeds = self.model.get_input_embeddings(ids, mask=data["mask"])
        else:
            pixels, grid = data["visual"]
            # Encode this image once, then reuse ONLY within this exact batch.
            features, _ = self.model.vision_tower(pixels.astype(self.model.vision_tower.patch_embed.proj.weight.dtype), grid)
            features = mx.tile(features, (len(hypotheses), 1))
            embeds = self.model.get_input_embeddings(ids, pixels, mask=data["mask"],
                image_grid_thw=mx.tile(grid, (len(hypotheses), 1)), cached_image_features=features)
        prefix = 0
        if share_prefix and len(hypotheses)>1:
            tokens = data["numpy_ids"]
            limit = int(data["numpy_mask"].sum(-1).min())-1
            while prefix<limit and (tokens[:,prefix]==tokens[0,prefix]).all():
                prefix += 1
        positions = embeds.position_ids
        cache = None
        if prefix:
            cache = self.model.language_model.make_cache()
            # One shared prefix for THIS frame only. Hybrid recurrent states
            # must be cloned across candidates, just like attention K/V states.
            self.model.language_model.model(ids[:1,:prefix],
                inputs_embeds=None if embeds.inputs_embeds is None else embeds.inputs_embeds[:1,:prefix], cache=cache,
                position_ids=None if positions is None else positions[...,:1,:prefix])
            from mlx_vlm.models.cache import ArraysCache, KVCache
            branched=[]
            for entry in cache:
                if isinstance(entry,ArraysCache):
                    branch=ArraysCache(size=len(entry.cache))
                    branch.cache=[None if x is None else mx.repeat(x,len(hypotheses),axis=0) for x in entry.cache]
                elif isinstance(entry,KVCache):
                    branch=KVCache()
                    branch.state=tuple(mx.repeat(x,len(hypotheses),axis=0) for x in entry.state)
                else:
                    raise TypeError("Unreviewed hybrid cache type")
                branched.append(branch)
            cache=branched
        hidden = self.model.language_model.model(ids[:,prefix:], inputs_embeds=None if embeds.inputs_embeds is None else embeds.inputs_embeds[:,prefix:],
            position_ids=None if positions is None else positions[...,prefix:], cache=cache)
        pooled = hidden[mx.arange(len(hypotheses)), data["lengths"] - prefix - 1]
        logits = self.model.score(pooled).astype(mx.float32)
        probabilities = mx.softmax(logits, axis=-1)
        mx.eval(probabilities)
        rows = probabilities.tolist()
        ranked = sorted(range(len(rows)), key=lambda i: rows[i][1], reverse=True)
        return {"choice": ranked[0], "support": [r[1] for r in rows], "nli": rows,
                "seconds": time.monotonic() - started, "tokens": int(ids.shape[1]), "shared_tokens":prefix,
                "prepare_seconds":prepared_at-started,
                "active_memory_mb":round(mx.get_active_memory()/1048576,1),
                "cache_memory_mb":round(mx.get_cache_memory()/1048576,1),
                "model": self.identity}
