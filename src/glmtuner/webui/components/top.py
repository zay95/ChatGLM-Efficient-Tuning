from typing import Dict

import gradio as gr
from gradio.components import Component

from glmtuner.extras.constants import METHODS, SUPPORTED_MODELS
from glmtuner.webui.common import list_checkpoint, get_model_path, save_config
from glmtuner.webui.utils import can_quantize


def create_top() -> Dict[str, Component]:
    available_models = list(SUPPORTED_MODELS.keys()) + ["Custom"]

    with gr.Row():
        lang = gr.Dropdown(choices=["en", "zh"], value="en", scale=1)
        model_name = gr.Dropdown(choices=available_models, scale=3)
        model_path = gr.Textbox(scale=3)

    with gr.Row():
        finetuning_type = gr.Dropdown(value="lora", choices=METHODS, scale=1)
        checkpoints = gr.Dropdown(multiselect=True, scale=5)
        refresh_btn = gr.Button(scale=1)

    with gr.Row():
        quantization_bit = gr.Dropdown([8, 4], scale=1)
        source_prefix = gr.Textbox(scale=6)

    model_name.change(
        get_model_path, [model_name], [model_path]
    ).then(
        list_checkpoint, [model_name, finetuning_type], [checkpoints]
    ) # do not save config since the below line will save
    model_path.change(save_config, [model_name, model_path])

    finetuning_type.change(
        list_checkpoint, [model_name, finetuning_type], [checkpoints]
    ).then(
        can_quantize, [finetuning_type], [quantization_bit]
    )

    refresh_btn.click(list_checkpoint, [model_name, finetuning_type], [checkpoints])

    return dict(
        lang=lang,
        model_name=model_name,
        model_path=model_path,
        finetuning_type=finetuning_type,
        checkpoints=checkpoints,
        refresh_btn=refresh_btn,
        quantization_bit=quantization_bit,
        source_prefix=source_prefix
    )
