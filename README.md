# Niutonan_Comfyui_Philips_Hue

ComfyUI custom nodes that sample the edge colors of generated images and send
matching colors to Philips Hue lights or Hue light strips.

Finally, ComfyUI is entering the physical world. Now you can control your home
lights directly from a ComfyUI workflow.

It is easy: generate an image, let the node read the image edges, and have your
lights match the mood of the result.

The package includes a full advanced node, a simpler everyday node, and a Hue
setup node for bridge registration and light discovery.

## Nodes

### Niutonan: Hue Setup

Use this node to find your Hue bridge, register an API key, list lights, and
test the connection.

Actions:

- `auto_scan`: finds Hue bridge IP addresses.
- `register_new`: registers this ComfyUI node with a Hue bridge.
- `check_connection`: checks the saved API key.
- `list_lights`: lists numeric Hue light IDs.
- `test_flash`: flashes all lights on the selected bridge.

### Niutonan: ComfyUI Hue Edge Bar simple

Recommended node for normal use.

Inputs:

- `image`: ComfyUI image input.
- `bridge_ip`: Hue bridge IP, for example `192.168.0.57`.
- `api_key`: optional. Leave blank after setup.
- `light_id`: Hue light ID, `all`, or `group:<id>`.
- `mode`: `send`, `preview_only`, or `turn_off`.
- `brightness`: Hue brightness from `1` to `254`.
- `edge_width`: how many pixels from the image border to sample.
- `transitiontime`: fade time in 1/10 second units. `6` means 0.6 seconds.

The simple node uses good defaults internally:

- Hue `xy` color for better color matching.
- Dominant edge color selection.
- Mild border filtering.
- Slight crop to avoid hard image borders.
- Mild vibrance and saturation shaping.

### Niutonan: ComfyUI Hue Edge Bar

Advanced node with additional controls:

- `color_api`: `xy` or `hue_sat`.
- `color_pick_mode`: `average`, `weighted_average`, `dominant`, `brightest`.
- `brightness_mode`: `fixed`, `from_image`, `from_image_clamped`.
- `crop_percent`
- `ignore_dark_below`
- `ignore_bright_above`
- `saturation_boost`
- `vibrance`
- `min_saturation`
- `max_saturation`
- `top_weight`, `right_weight`, `bottom_weight`, `left_weight`
- `transitiontime`

## Installation

Copy this folder into your ComfyUI custom nodes directory:

```text
ComfyUI/custom_nodes/Niutonan_Comfyui_Philips_Hue
```

For ComfyUI portable on Windows, that often looks like:

```text
ComfyUI_windows_portable/ComfyUI/custom_nodes/Niutonan_Comfyui_Philips_Hue
```

Restart ComfyUI after copying the folder.

No extra Python packages are required.

## Step-by-Step Hue Setup

### 1. Find Your Hue Bridge

Add the node:

```text
Niutonan: Hue Setup
```

Set:

```text
bridge_ip = auto
action = auto_scan
```

Queue the prompt.

The output should look similar to:

```text
Found Hue bridge(s):
192.168.0.57 (meethue)
```

If more than one bridge is found, choose the one that controls your Hue strip or
room lights. Put that exact IP into `bridge_ip` for the next steps.

### 2. Register ComfyUI With the Hue Bridge

Press the physical button on top of the Philips Hue Bridge.

Then run `Niutonan: Hue Setup` with:

```text
bridge_ip = 192.168.0.57
action = register_new
```

Replace `192.168.0.57` with your bridge IP.

If registration succeeds, the node saves an API key in:

```text
Niutonan_Comfyui_Philips_Hue/hue_config.json
```

Do not upload `hue_config.json` to GitHub. It is ignored by this repository's
`.gitignore`.

### 3. List Your Hue Lights

Run `Niutonan: Hue Setup` with:

```text
bridge_ip = 192.168.0.57
action = list_lights
```

The output will include light IDs:

```text
1: Hue lightstrip plus [ON]
2: Desk lamp [OFF]
3: Hue play bar [ON]
```

Write down the numeric ID for the light or strip you want to control.

### 4. Test the Bridge

Run:

```text
bridge_ip = 192.168.0.57
action = test_flash
```

Your Hue lights should flash briefly.

### 5. Use the Simple Edge Bar Node

Add:

```text
Niutonan: ComfyUI Hue Edge Bar simple
```

Connect your generated image to the `image` input.

Recommended settings:

```text
bridge_ip = 192.168.0.57
api_key =
light_id = 1
mode = send
brightness = 180
edge_width = 32
transitiontime = 6
```

Leave `api_key` blank. The node loads the saved key from `hue_config.json`.

Use your actual `light_id` from the `list_lights` step.

## Controlling Multiple Lights

The `light_id` field accepts:

```text
1
```

Controls a specific light by ID.

```text
all
```

Controls all lights on the bridge.

```text
group:3
```

Controls Hue group ID `3`.

To find group IDs, use the Hue app or the Hue API. The setup node currently
lists lights, not groups.

## Recommended Settings

For most users:

```text
Node: Niutonan: ComfyUI Hue Edge Bar simple
mode = send
brightness = 160 to 210
edge_width = 24 to 48
transitiontime = 6 to 12
```

If the light feels too jumpy, increase `transitiontime`.

If colors feel too influenced by black image borders, increase `edge_width` or
use the advanced node with `ignore_dark_below`.

If colors feel too gray, use the advanced node and increase `vibrance` or
`saturation_boost`.

## How Color Output Works

The node samples colors around the image perimeter and builds a virtual LED bar.
Standard Philips Hue v1 light control accepts one active color per light or
group, so the node sends one selected edge color to the selected Hue light.

The node also returns:

- `edge_bar_json`: the virtual LED bar and debug data.
- `average_rgb`: the final RGB color sent through the Hue conversion.

## Troubleshooting

### Auto Scan Finds Multiple Bridges

Use the exact bridge IP instead of `auto`.

Example:

```text
bridge_ip = 192.168.0.57
```

### Register Says to Press the Button

Press the physical Hue Bridge button and run `register_new` again within about
30 seconds.

### No API Key Found

Run:

```text
Niutonan: Hue Setup
action = register_new
```

Then leave `api_key` blank in the edge bar node.

### Light Does Not Change Color

Check:

- The bridge IP is correct.
- The `light_id` matches the Hue strip or light.
- `mode` is set to `send`.
- The light is reachable in the Hue app.
- `test_flash` works from the setup node.

### Colors Look Wrong

Try:

- Use `Niutonan: ComfyUI Hue Edge Bar simple` first.
- Increase `transitiontime` for smoother fades.
- Try the advanced node with `color_pick_mode = weighted_average`.
- Use `color_api = xy` for better Hue color matching.

## Security Notes

The Hue API key allows local control of your Hue bridge. Keep this file private:

```text
hue_config.json
```

Do not commit it to GitHub.

## Compatibility

- Philips Hue Bridge local v1 API.
- ComfyUI custom node system.
- Windows portable ComfyUI and normal ComfyUI installs.

No third-party Python dependencies are required.
