"""Niutonan ComfyUI Philips Hue nodes.

Extracts edge colors from generated images and sends the averaged edge color
to a Philips Hue bridge using the local Hue v1 API.
"""

from __future__ import annotations

import colorsys
import json
import os
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import ip_network
from typing import Any

import numpy as np


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
HUE_CONFIG_FILE = os.path.join(THIS_DIR, "hue_config.json")


def load_hue_config() -> dict[str, Any]:
    if os.path.exists(HUE_CONFIG_FILE):
        try:
            with open(HUE_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            print(f"[Niutonan Hue] Failed to load config: {exc}")
    return {}


def save_hue_config(config: dict[str, Any]) -> bool:
    try:
        with open(HUE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as exc:
        print(f"[Niutonan Hue] Failed to save config: {exc}")
        return False


def get_hue_api_key(bridge_ip: str) -> str:
    value = normalize_bridge_ip(bridge_ip)
    if value.lower() in {"auto", "scan", "discover"}:
        resolved_ip, _ = resolve_bridge_ip(value)
        value = resolved_ip or value
    return load_hue_config().get(value, {}).get("api_key", "")


def normalize_bridge_ip(bridge_ip: str) -> str:
    return str(bridge_ip or "").strip()


def discover_hue_bridges(timeout: float = 2.0) -> list[dict[str, str]]:
    bridges: dict[str, dict[str, str]] = {}

    for bridge in discover_hue_bridges_cloud(timeout=timeout):
        bridges[bridge["ip"]] = bridge

    for bridge in discover_hue_bridges_ssdp(timeout=timeout):
        bridges.setdefault(bridge["ip"], bridge)

    if not bridges:
        for bridge in discover_hue_bridges_subnet(timeout=timeout):
            bridges.setdefault(bridge["ip"], bridge)

    return sorted(bridges.values(), key=lambda item: item["ip"])


def discover_hue_bridges_cloud(timeout: float = 2.0) -> list[dict[str, str]]:
    try:
        response = urllib.request.urlopen("https://discovery.meethue.com/", timeout=timeout)
        result = json.loads(response.read().decode("utf-8"))
        bridges = []
        for item in result if isinstance(result, list) else []:
            ip = item.get("internalipaddress")
            if ip:
                bridges.append({"ip": ip, "id": item.get("id", ""), "source": "meethue"})
        return bridges
    except Exception as exc:
        print(f"[Niutonan Hue] Cloud discovery failed: {exc}")
        return []


def discover_hue_bridges_ssdp(timeout: float = 2.0) -> list[dict[str, str]]:
    message = "\r\n".join(
        [
            "M-SEARCH * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            'MAN: "ssdp:discover"',
            "MX: 1",
            "ST: ssdp:all",
            "",
            "",
        ]
    ).encode("ascii")
    bridges: dict[str, dict[str, str]] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(0.4)
        sock.sendto(message, ("239.255.255.250", 1900))
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            text = data.decode("utf-8", errors="ignore").lower()
            if "hue" in text or "ipbridge" in text or "philips" in text:
                bridges[addr[0]] = {"ip": addr[0], "id": "", "source": "ssdp"}
    except Exception as exc:
        print(f"[Niutonan Hue] SSDP discovery failed: {exc}")
    finally:
        sock.close()

    return list(bridges.values())


def get_local_ipv4() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None
    finally:
        sock.close()


def is_hue_bridge_at(ip: str, timeout: float = 0.35) -> bool:
    try:
        response = urllib.request.urlopen(f"http://{ip}/description.xml", timeout=timeout)
        text = response.read(8192).decode("utf-8", errors="ignore").lower()
        return "philips hue" in text or "ipbridge" in text or "hue bridge" in text
    except Exception:
        return False


def discover_hue_bridges_subnet(timeout: float = 2.0) -> list[dict[str, str]]:
    local_ip = get_local_ipv4()
    if not local_ip:
        return []

    network = ip_network(f"{local_ip}/24", strict=False)
    candidates = [str(ip) for ip in network.hosts()]
    found: list[dict[str, str]] = []
    deadline = time.time() + timeout

    with ThreadPoolExecutor(max_workers=32) as executor:
        futures = {executor.submit(is_hue_bridge_at, ip): ip for ip in candidates}
        for future in as_completed(futures):
            if time.time() > deadline and found:
                break
            ip = futures[future]
            try:
                if future.result():
                    found.append({"ip": ip, "id": "", "source": "subnet"})
            except Exception:
                pass

    return found


def resolve_bridge_ip(bridge_ip: str) -> tuple[str | None, str | None]:
    value = normalize_bridge_ip(bridge_ip)
    if value and value.lower() not in {"auto", "scan", "discover"}:
        return value, None

    bridges = discover_hue_bridges(timeout=2.0)
    if not bridges:
        return None, "No Hue bridge found. Enter bridge_ip manually or check that the bridge is on this network."
    if len(bridges) > 1:
        lines = [f"{bridge['ip']} ({bridge['source']})" for bridge in bridges]
        return None, "Multiple Hue bridges found. Put one of these in bridge_ip:\n" + "\n".join(lines)
    return bridges[0]["ip"], None


def register_hue_user(bridge_ip: str) -> tuple[str | None, str | None]:
    bridge_ip, error = resolve_bridge_ip(bridge_ip)
    if not bridge_ip:
        return None, error

    try:
        url = f"http://{bridge_ip}/api"
        data = json.dumps({"devicetype": "Niutonan_Comfyui_Philips_Hue#comfyui"}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        response = urllib.request.urlopen(req, timeout=10)
        result = json.loads(response.read().decode("utf-8"))

        if result and isinstance(result, list):
            item = result[0]
            if "success" in item:
                api_key = item["success"]["username"]
                config = load_hue_config()
                config[bridge_ip] = {"api_key": api_key}
                save_hue_config(config)
                return api_key, None
            if "error" in item:
                error = item["error"]
                if error.get("type") == 101:
                    return None, "Press the Hue bridge button, then run register again."
                return None, error.get("description", "Unknown Hue bridge error")
        return None, "Unexpected Hue bridge response"
    except Exception as exc:
        return None, str(exc)


def get_hue_lights(bridge_ip: str, api_key: str) -> dict[str, Any]:
    bridge_ip, error = resolve_bridge_ip(bridge_ip)
    if not bridge_ip:
        print(f"[Niutonan Hue] {error}")
        return {}

    try:
        url = f"http://{bridge_ip}/api/{api_key}/lights"
        response = urllib.request.urlopen(urllib.request.Request(url), timeout=5)
        result = json.loads(response.read().decode("utf-8"))
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        print(f"[Niutonan Hue] Failed to list lights: {exc}")
        return {}


def send_hue_command(bridge_ip: str, api_key: str, light_id: str, command: dict[str, Any]) -> bool:
    bridge_ip, error = resolve_bridge_ip(bridge_ip)
    if not bridge_ip:
        print(f"[Niutonan Hue] {error}")
        return False

    try:
        target = str(light_id).strip()
        if target.lower() == "all":
            url = f"http://{bridge_ip}/api/{api_key}/groups/0/action"
        elif target.lower().startswith("group:"):
            group_id = target.split(":", 1)[1]
            url = f"http://{bridge_ip}/api/{api_key}/groups/{group_id}/action"
        else:
            url = f"http://{bridge_ip}/api/{api_key}/lights/{target}/state"

        data = json.dumps(command).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="PUT")
        req.add_header("Content-Type", "application/json")
        response = urllib.request.urlopen(req, timeout=5)
        result = json.loads(response.read().decode("utf-8"))
        print(f"[Niutonan Hue] Hue response: {result}")
        return True
    except Exception as exc:
        print(f"[Niutonan Hue] Hue command failed: {exc}")
        return False


def tensor_to_rgb_uint8(image: Any, batch_index: int = 0) -> np.ndarray:
    img_tensor = image[min(max(batch_index, 0), image.shape[0] - 1)]
    img_np = (img_tensor.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)

    if img_np.ndim == 2:
        img_np = np.stack([img_np, img_np, img_np], axis=-1)
    elif img_np.shape[-1] == 1:
        img_np = np.repeat(img_np, 3, axis=-1)
    elif img_np.shape[-1] > 3:
        img_np = img_np[..., :3]
    return img_np


def crop_image(img_np: np.ndarray, crop_percent: float) -> np.ndarray:
    crop_percent = max(0.0, min(float(crop_percent), 45.0))
    if crop_percent <= 0:
        return img_np

    height, width, _ = img_np.shape
    crop_x = int(round(width * (crop_percent / 100.0)))
    crop_y = int(round(height * (crop_percent / 100.0)))
    if crop_x * 2 >= width or crop_y * 2 >= height:
        return img_np
    return img_np[crop_y : height - crop_y, crop_x : width - crop_x, :]


def filter_pixels(samples: np.ndarray, ignore_dark_below: int, ignore_bright_above: int) -> np.ndarray:
    if samples.size == 0:
        return samples

    pixels = samples.reshape(-1, 3)
    luminance = pixels[:, 0] * 0.2126 + pixels[:, 1] * 0.7152 + pixels[:, 2] * 0.0722
    dark_limit = max(0, min(int(ignore_dark_below), 255))
    bright_limit = max(0, min(int(ignore_bright_above), 255))
    if bright_limit <= 0:
        bright_limit = 255

    mask = (luminance >= dark_limit) & (luminance <= bright_limit)
    filtered = pixels[mask]
    return filtered if filtered.size else pixels


def edge_segments(img_np: np.ndarray, edge_width: int) -> dict[str, np.ndarray]:
    height, width, _ = img_np.shape
    edge_width = max(1, min(edge_width, max(1, min(width, height) // 2)))

    return {
        "top": img_np[:edge_width, :, :].mean(axis=0),
        "right": img_np[:, width - edge_width :, :].mean(axis=1),
        "bottom": img_np[height - edge_width :, :, :].mean(axis=0)[::-1],
        "left": img_np[:, :edge_width, :].mean(axis=1)[::-1],
    }


def perimeter_samples(
    img_np: np.ndarray,
    edge_width: int,
    crop_percent: float = 0.0,
    ignore_dark_below: int = 0,
    ignore_bright_above: int = 255,
) -> np.ndarray:
    cropped = crop_image(img_np, crop_percent)
    segments = edge_segments(cropped, edge_width)
    samples = [
        filter_pixels(segment, ignore_dark_below, ignore_bright_above)
        for segment in (segments["top"], segments["right"], segments["bottom"], segments["left"])
    ]
    return np.concatenate(samples, axis=0)


def weighted_edge_average(
    img_np: np.ndarray,
    edge_width: int,
    crop_percent: float,
    ignore_dark_below: int,
    ignore_bright_above: int,
    top_weight: float,
    right_weight: float,
    bottom_weight: float,
    left_weight: float,
) -> tuple[int, int, int]:
    cropped = crop_image(img_np, crop_percent)
    segments = edge_segments(cropped, edge_width)
    weighted_colors = []
    weights = []
    for name, weight in (
        ("top", top_weight),
        ("right", right_weight),
        ("bottom", bottom_weight),
        ("left", left_weight),
    ):
        weight = max(0.0, float(weight))
        if weight <= 0:
            continue
        pixels = filter_pixels(segments[name], ignore_dark_below, ignore_bright_above)
        weighted_colors.append(pixels.mean(axis=0))
        weights.append(weight)

    if not weighted_colors:
        return average_rgb(make_led_bar(cropped, edge_width=edge_width, led_count=1))

    rgb = np.average(np.array(weighted_colors), axis=0, weights=np.array(weights))
    rgb = rgb.clip(0, 255).round().astype(np.uint8).tolist()
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def make_led_bar(
    img_np: np.ndarray,
    edge_width: int,
    led_count: int,
    crop_percent: float = 0.0,
    ignore_dark_below: int = 0,
    ignore_bright_above: int = 255,
) -> list[list[int]]:
    samples = perimeter_samples(img_np, edge_width, crop_percent, ignore_dark_below, ignore_bright_above)
    led_count = max(1, int(led_count))
    chunks = np.array_split(samples, led_count)
    colors = [chunk.mean(axis=0).clip(0, 255).round().astype(np.uint8).tolist() for chunk in chunks]
    return colors


def average_rgb(colors: list[list[int]]) -> tuple[int, int, int]:
    arr = np.array(colors, dtype=np.float32)
    rgb = arr.mean(axis=0).clip(0, 255).round().astype(np.uint8).tolist()
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def dominant_rgb(colors: list[list[int]]) -> tuple[int, int, int]:
    pixels = np.array(colors, dtype=np.uint8).reshape(-1, 3)
    if pixels.size == 0:
        return 0, 0, 0

    bins = (pixels.astype(np.uint16) // 32).astype(np.uint16)
    keys, inverse, counts = np.unique(bins, axis=0, return_inverse=True, return_counts=True)
    best_index = int(np.argmax(counts))
    cluster = pixels[inverse == best_index]
    rgb = cluster.mean(axis=0).clip(0, 255).round().astype(np.uint8).tolist()
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def brightest_rgb(colors: list[list[int]]) -> tuple[int, int, int]:
    pixels = np.array(colors, dtype=np.uint8).reshape(-1, 3)
    luminance = pixels[:, 0] * 0.2126 + pixels[:, 1] * 0.7152 + pixels[:, 2] * 0.0722
    rgb = pixels[int(np.argmax(luminance))].tolist()
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def choose_rgb(
    led_bar: list[list[int]],
    color_pick_mode: str,
    weighted_rgb: tuple[int, int, int],
) -> tuple[int, int, int]:
    if color_pick_mode == "dominant":
        return dominant_rgb(led_bar)
    if color_pick_mode == "brightest":
        return brightest_rgb(led_bar)
    if color_pick_mode == "weighted_average":
        return weighted_rgb
    return average_rgb(led_bar)


def apply_color_shaping(
    rgb: tuple[int, int, int],
    saturation_boost: float,
    min_saturation: float,
    max_saturation: float,
    vibrance: float,
) -> tuple[int, int, int]:
    r, g, b = [channel / 255.0 for channel in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    shaped_boost = max(0.0, saturation_boost) + (max(0.0, vibrance) * (1.0 - s))
    s = s * shaped_boost
    s = max(0.0, min(1.0, s))
    s = max(max(0.0, min_saturation / 100.0), s)
    s = min(max(0.0, min(max_saturation / 100.0, 1.0)), s)
    boosted = colorsys.hsv_to_rgb(h, s, v)
    return tuple(int(round(channel * 255.0)) for channel in boosted)


def rgb_luminance(rgb: tuple[int, int, int]) -> float:
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722


def choose_brightness(
    rgb: tuple[int, int, int],
    brightness_mode: str,
    brightness: int,
    min_brightness: int,
    max_brightness: int,
) -> int:
    fixed = max(1, min(int(brightness), 254))
    low = max(1, min(int(min_brightness), 254))
    high = max(low, min(int(max_brightness), 254))
    if brightness_mode == "from_image":
        return max(1, min(int(round((rgb_luminance(rgb) / 255.0) * 254.0)), 254))
    if brightness_mode == "from_image_clamped":
        value = int(round(low + (rgb_luminance(rgb) / 255.0) * (high - low)))
        return max(low, min(value, high))
    return fixed


def rgb_to_hue_sat_command(rgb: tuple[int, int, int], brightness: int) -> dict[str, Any]:
    r, g, b = [channel / 255.0 for channel in rgb]
    h, s, _ = colorsys.rgb_to_hsv(r, g, b)
    hue = int(round(h * 65535)) % 65536
    sat = int(round(s * 254))
    return {"on": True, "bri": int(brightness), "hue": hue, "sat": sat}


def srgb_to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def rgb_to_xy(rgb: tuple[int, int, int]) -> tuple[float, float]:
    r, g, b = [srgb_to_linear(channel / 255.0) for channel in rgb]
    x_value = r * 0.664511 + g * 0.154324 + b * 0.162028
    y_value = r * 0.283881 + g * 0.668433 + b * 0.047685
    z_value = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = x_value + y_value + z_value
    if total <= 0:
        return 0.3227, 0.3290
    return x_value / total, y_value / total


def rgb_to_hue_command(
    rgb: tuple[int, int, int],
    brightness: int,
    color_api: str = "xy",
    transitiontime: int = 4,
) -> dict[str, Any]:
    command: dict[str, Any] = {"on": True, "bri": int(brightness)}
    transitiontime = max(0, min(int(transitiontime), 6000))
    if transitiontime > 0:
        command["transitiontime"] = transitiontime

    if color_api == "hue_sat":
        command.update(rgb_to_hue_sat_command(rgb, brightness))
    else:
        x_value, y_value = rgb_to_xy(rgb)
        command["xy"] = [round(x_value, 4), round(y_value, 4)]
    return command


class Niutonan_Comfyui_Philips_Hue:
    """Average image-edge colors into a virtual LED bar and push to Hue."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "bridge_ip": ("STRING", {"default": "auto", "multiline": False}),
                "api_key": ("STRING", {"default": "", "multiline": False}),
                "light_id": ("STRING", {"default": "1", "multiline": False}),
                "mode": (["send_average", "preview_only", "turn_off"], {"default": "send_average"}),
            },
            "optional": {
                "color_pick_mode": (["average", "weighted_average", "dominant", "brightest"], {"default": "average"}),
                "color_api": (["xy", "hue_sat"], {"default": "xy"}),
                "brightness_mode": (["fixed", "from_image", "from_image_clamped"], {"default": "fixed"}),
                "led_count": ("INT", {"default": 24, "min": 1, "max": 300}),
                "edge_width": ("INT", {"default": 32, "min": 1, "max": 512}),
                "crop_percent": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 45.0, "step": 0.5}),
                "ignore_dark_below": ("INT", {"default": 0, "min": 0, "max": 255}),
                "ignore_bright_above": ("INT", {"default": 255, "min": 0, "max": 255}),
                "brightness": ("INT", {"default": 180, "min": 1, "max": 254}),
                "min_brightness": ("INT", {"default": 40, "min": 1, "max": 254}),
                "max_brightness": ("INT", {"default": 220, "min": 1, "max": 254}),
                "saturation_boost": ("FLOAT", {"default": 1.15, "min": 0.0, "max": 3.0, "step": 0.05}),
                "min_saturation": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 100.0, "step": 1.0}),
                "max_saturation": ("FLOAT", {"default": 100.0, "min": 0.0, "max": 100.0, "step": 1.0}),
                "vibrance": ("FLOAT", {"default": 0.20, "min": 0.0, "max": 2.0, "step": 0.05}),
                "transitiontime": ("INT", {"default": 6, "min": 0, "max": 6000}),
                "top_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "right_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "bottom_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "left_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "batch_index": ("INT", {"default": 0, "min": 0, "max": 999}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "edge_bar_json", "average_rgb")
    FUNCTION = "execute"
    CATEGORY = "Niutonan/Philips Hue"
    OUTPUT_NODE = True

    def execute(
        self,
        image,
        bridge_ip,
        api_key,
        light_id,
        mode,
        color_pick_mode="average",
        color_api="xy",
        brightness_mode="fixed",
        led_count=24,
        edge_width=32,
        crop_percent=0.0,
        ignore_dark_below=0,
        ignore_bright_above=255,
        brightness=180,
        min_brightness=40,
        max_brightness=220,
        saturation_boost=1.15,
        min_saturation=0.0,
        max_saturation=100.0,
        vibrance=0.20,
        transitiontime=6,
        top_weight=1.0,
        right_weight=1.0,
        bottom_weight=1.0,
        left_weight=1.0,
        batch_index=0,
    ):
        img_np = tensor_to_rgb_uint8(image, batch_index=batch_index)
        led_bar = make_led_bar(
            img_np,
            edge_width=edge_width,
            led_count=led_count,
            crop_percent=crop_percent,
            ignore_dark_below=ignore_dark_below,
            ignore_bright_above=ignore_bright_above,
        )
        weighted_rgb = weighted_edge_average(
            img_np,
            edge_width=edge_width,
            crop_percent=crop_percent,
            ignore_dark_below=ignore_dark_below,
            ignore_bright_above=ignore_bright_above,
            top_weight=top_weight,
            right_weight=right_weight,
            bottom_weight=bottom_weight,
            left_weight=left_weight,
        )
        raw_rgb = choose_rgb(led_bar, color_pick_mode, weighted_rgb)
        rgb = apply_color_shaping(raw_rgb, saturation_boost, min_saturation, max_saturation, vibrance)
        final_brightness = choose_brightness(rgb, brightness_mode, brightness, min_brightness, max_brightness)

        if mode == "turn_off":
            resolved_key = api_key or get_hue_api_key(bridge_ip)
            if resolved_key:
                send_hue_command(bridge_ip, resolved_key, light_id, {"on": False})
        elif mode == "send_average":
            resolved_key = api_key or get_hue_api_key(bridge_ip)
            if not resolved_key:
                print("[Niutonan Hue] No API key. Use Niutonan Hue Setup to register first.")
            else:
                command = rgb_to_hue_command(rgb, final_brightness, color_api, transitiontime)
                send_hue_command(bridge_ip, resolved_key, light_id, command)

        bar_json = json.dumps(
            {
                "led_count": len(led_bar),
                "colors": led_bar,
                "raw_rgb": list(raw_rgb),
                "shaped_rgb": list(rgb),
                "brightness": final_brightness,
                "color_pick_mode": color_pick_mode,
                "color_api": color_api,
            }
        )
        rgb_text = f"{rgb[0]},{rgb[1]},{rgb[2]}"
        print(
            f"[Niutonan Hue] Edge RGB: {rgb_text}, brightness={final_brightness}, "
            f"mode={color_pick_mode}, api={color_api}, leds={len(led_bar)}"
        )
        return (image, bar_json, rgb_text)


class Niutonan_Comfyui_Philips_Hue_Simple:
    """Simplified edge-color Hue node with opinionated defaults."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "bridge_ip": ("STRING", {"default": "192.168.0.57", "multiline": False}),
                "api_key": ("STRING", {"default": "", "multiline": False}),
                "light_id": ("STRING", {"default": "1", "multiline": False}),
                "mode": (["send", "preview_only", "turn_off"], {"default": "send"}),
            },
            "optional": {
                "brightness": ("INT", {"default": 180, "min": 1, "max": 254}),
                "edge_width": ("INT", {"default": 32, "min": 1, "max": 512}),
                "transitiontime": ("INT", {"default": 6, "min": 0, "max": 6000}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "edge_bar_json", "average_rgb")
    FUNCTION = "execute"
    CATEGORY = "Niutonan/Philips Hue"
    OUTPUT_NODE = True

    def execute(
        self,
        image,
        bridge_ip,
        api_key,
        light_id,
        mode,
        brightness=180,
        edge_width=32,
        transitiontime=6,
    ):
        img_np = tensor_to_rgb_uint8(image, batch_index=0)
        led_bar = make_led_bar(
            img_np,
            edge_width=edge_width,
            led_count=24,
            crop_percent=1.0,
            ignore_dark_below=8,
            ignore_bright_above=250,
        )
        weighted_rgb = weighted_edge_average(
            img_np,
            edge_width=edge_width,
            crop_percent=1.0,
            ignore_dark_below=8,
            ignore_bright_above=250,
            top_weight=1.0,
            right_weight=1.0,
            bottom_weight=1.0,
            left_weight=1.0,
        )
        raw_rgb = choose_rgb(led_bar, "dominant", weighted_rgb)
        rgb = apply_color_shaping(
            raw_rgb,
            saturation_boost=1.20,
            min_saturation=8.0,
            max_saturation=100.0,
            vibrance=0.25,
        )

        if mode == "turn_off":
            resolved_key = api_key or get_hue_api_key(bridge_ip)
            if resolved_key:
                send_hue_command(bridge_ip, resolved_key, light_id, {"on": False})
        elif mode == "send":
            resolved_key = api_key or get_hue_api_key(bridge_ip)
            if not resolved_key:
                print("[Niutonan Hue Simple] No API key. Use Niutonan Hue Setup to register first.")
            else:
                command = rgb_to_hue_command(rgb, brightness, color_api="xy", transitiontime=transitiontime)
                send_hue_command(bridge_ip, resolved_key, light_id, command)

        bar_json = json.dumps(
            {
                "led_count": len(led_bar),
                "colors": led_bar,
                "raw_rgb": list(raw_rgb),
                "shaped_rgb": list(rgb),
                "brightness": int(brightness),
                "color_pick_mode": "dominant",
                "color_api": "xy",
                "simple": True,
            }
        )
        rgb_text = f"{rgb[0]},{rgb[1]},{rgb[2]}"
        print(f"[Niutonan Hue Simple] Edge RGB: {rgb_text}, brightness={brightness}, leds={len(led_bar)}")
        return (image, bar_json, rgb_text)


class Niutonan_Comfyui_Philips_Hue_Setup:
    """Register and inspect Hue bridge access for Niutonan_Comfyui_Philips_Hue."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bridge_ip": ("STRING", {"default": "auto", "multiline": False}),
                "action": (["auto_scan", "check_connection", "register_new", "list_lights", "test_flash"],),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("result",)
    FUNCTION = "execute"
    CATEGORY = "Niutonan/Philips Hue"
    OUTPUT_NODE = True

    def execute(self, bridge_ip, action):
        result = ""

        if action == "auto_scan":
            bridges = discover_hue_bridges(timeout=3.0)
            if bridges:
                lines = [f"{bridge['ip']} ({bridge['source']})" for bridge in bridges]
                result = "Found Hue bridge(s):\n" + "\n".join(lines)
            else:
                result = "No Hue bridge found. Check network access or enter bridge_ip manually."
        elif action == "register_new":
            resolved_ip, resolve_error = resolve_bridge_ip(bridge_ip)
            if not resolved_ip:
                result = f"ERROR: {resolve_error}"
            else:
                api_key, error = register_hue_user(resolved_ip)
                result = f"SUCCESS: API key saved for {resolved_ip}: {api_key}" if api_key else f"ERROR: {error}"
        elif action == "check_connection":
            resolved_ip, resolve_error = resolve_bridge_ip(bridge_ip)
            if not resolved_ip:
                result = f"ERROR: {resolve_error}"
                print(f"[Niutonan Hue Setup] {result}")
                return (result,)
            api_key = get_hue_api_key(resolved_ip)
            if not api_key:
                result = f"No saved API key for {resolved_ip}. Press the bridge button and run register_new."
            else:
                lights = get_hue_lights(resolved_ip, api_key)
                result = f"Connected to {resolved_ip}. Found {len(lights)} lights." if lights else "API key found, but no lights returned."
        elif action == "list_lights":
            resolved_ip, resolve_error = resolve_bridge_ip(bridge_ip)
            if not resolved_ip:
                result = f"ERROR: {resolve_error}"
                print(f"[Niutonan Hue Setup] {result}")
                return (result,)
            api_key = get_hue_api_key(resolved_ip)
            if not api_key:
                result = f"No saved API key for {resolved_ip}. Press the bridge button and run register_new."
            else:
                lights = get_hue_lights(resolved_ip, api_key)
                lines = []
                for light_id, light in lights.items():
                    state = light.get("state", {})
                    on_off = "ON" if state.get("on") else "OFF"
                    lines.append(f"{light_id}: {light.get('name', 'Unknown')} [{on_off}]")
                result = "\n".join(lines) if lines else "No lights found."
        elif action == "test_flash":
            resolved_ip, resolve_error = resolve_bridge_ip(bridge_ip)
            if not resolved_ip:
                result = f"ERROR: {resolve_error}"
                print(f"[Niutonan Hue Setup] {result}")
                return (result,)
            api_key = get_hue_api_key(resolved_ip)
            if not api_key:
                result = f"No saved API key for {resolved_ip}. Press the bridge button and run register_new."
            else:
                ok = send_hue_command(resolved_ip, api_key, "all", {"alert": "select"})
                result = "Flashed all lights." if ok else "Hue test flash failed."

        print(f"[Niutonan Hue Setup] {result}")
        return (result,)


NODE_CLASS_MAPPINGS = {
    "Niutonan_Comfyui_Philips_Hue": Niutonan_Comfyui_Philips_Hue,
    "Niutonan_Comfyui_Philips_Hue_Simple": Niutonan_Comfyui_Philips_Hue_Simple,
    "Niutonan_Comfyui_Philips_Hue_Setup": Niutonan_Comfyui_Philips_Hue_Setup,
    "Niutonan_Comfyui_Hue": Niutonan_Comfyui_Philips_Hue,
    "Niutonan_Comfyui_Hue_Simple": Niutonan_Comfyui_Philips_Hue_Simple,
    "Niutonan_Comfyui_Hue_Setup": Niutonan_Comfyui_Philips_Hue_Setup,
    "Niutonian_comfyui_philips_hue": Niutonan_Comfyui_Philips_Hue,
    "Niutonian_comfyui_philips_hue_Simple": Niutonan_Comfyui_Philips_Hue_Simple,
    "Niutonian_comfyui_philips_hue_Setup": Niutonan_Comfyui_Philips_Hue_Setup,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Niutonan_Comfyui_Philips_Hue": "Niutonan: ComfyUI Hue Edge Bar",
    "Niutonan_Comfyui_Philips_Hue_Simple": "Niutonan: ComfyUI Hue Edge Bar simple",
    "Niutonan_Comfyui_Philips_Hue_Setup": "Niutonan: Hue Setup",
    "Niutonan_Comfyui_Hue": "Niutonan: ComfyUI Hue Edge Bar",
    "Niutonan_Comfyui_Hue_Simple": "Niutonan: ComfyUI Hue Edge Bar simple",
    "Niutonan_Comfyui_Hue_Setup": "Niutonan: Hue Setup",
    "Niutonian_comfyui_philips_hue": "Niutonan: ComfyUI Hue Edge Bar",
    "Niutonian_comfyui_philips_hue_Simple": "Niutonan: ComfyUI Hue Edge Bar simple",
    "Niutonian_comfyui_philips_hue_Setup": "Niutonan: Hue Setup",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
