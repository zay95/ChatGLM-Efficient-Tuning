import torch
from typing import Any, Dict, Generator, List, Optional, Tuple
from threading import Thread
from transformers import TextIteratorStreamer

from glmtuner.extras.misc import get_logits_processor
from glmtuner.extras.misc import auto_configure_device_map
from glmtuner.hparams import ModelArguments, DataArguments, FinetuningArguments, GeneratingArguments
from glmtuner.tuner import load_model_and_tokenizer


class ChatModel:

    def __init__(
        self,
        model_args: ModelArguments,
        data_args: DataArguments,
        finetuning_args: FinetuningArguments,
        generating_args: GeneratingArguments
    ) -> None:
        self.model, self.tokenizer = load_model_and_tokenizer(model_args, finetuning_args)

        if torch.cuda.device_count() > 1:
            from accelerate import dispatch_model
            device_map = auto_configure_device_map(torch.cuda.device_count(), use_v2=(self.tokenizer.eos_token_id==2))
            self.model = dispatch_model(self.model, device_map)
        else:
            self.model = self.model.cuda()

        self.source_prefix = data_args.source_prefix if data_args.source_prefix else ""
        self.generating_args = generating_args

    def get_prompt(
        self, query: str, history: Optional[List[Tuple[str, str]]] = None, prefix: Optional[str] = None
    ) -> str:
        prefix = prefix + "\n" if prefix else "" # add separator for non-empty prefix
        history = history if history else []
        prompt = ""
        for i, (old_query, response) in enumerate(history):
            prompt += "[Round {}]\n\n问：{}\n\n答：{}\n\n".format(i+1, old_query, response)
        prompt += "[Round {}]\n\n问：{}\n\n答：".format(len(history)+1, query)
        prompt = prefix + prompt
        return prompt

    def process_args(
        self, query: str, history: Optional[List[Tuple[str, str]]] = None, prefix: Optional[str] = None, **input_kwargs
    ) -> Tuple[Dict[str, Any], int]:
        prefix = prefix if prefix else self.source_prefix

        inputs = self.tokenizer([self.get_prompt(query, history, prefix)], return_tensors="pt")
        inputs = inputs.to(self.model.device)
        prompt_length = len(inputs["input_ids"][0])

        temperature = input_kwargs.pop("temperature", None)
        top_p = input_kwargs.pop("top_p", None)
        top_k = input_kwargs.pop("top_k", None)
        repetition_penalty = input_kwargs.pop("repetition_penalty", None)
        max_length = input_kwargs.pop("max_length", None)
        max_new_tokens = input_kwargs.pop("max_new_tokens", None)

        gen_kwargs = self.generating_args.to_dict()
        gen_kwargs.update(dict(
            input_ids=inputs["input_ids"],
            temperature=temperature or gen_kwargs["temperature"],
            top_p=top_p or gen_kwargs["top_p"],
            top_k=top_k or gen_kwargs["top_k"],
            repetition_penalty=repetition_penalty or gen_kwargs["repetition_penalty"],
            logits_processor=get_logits_processor()
        ))

        if max_length:
            gen_kwargs.pop("max_new_tokens", None)
            gen_kwargs["max_length"] = max_length

        if max_new_tokens:
            gen_kwargs.pop("max_length", None)
            gen_kwargs["max_new_tokens"] = max_new_tokens

        return gen_kwargs, prompt_length

    @torch.inference_mode()
    def chat(
        self, query: str, history: Optional[List[Tuple[str, str]]] = None, prefix: Optional[str] = None, **input_kwargs
    ) -> Tuple[str, Tuple[int, int]]:
        gen_kwargs, prompt_length = self.process_args(query, history, prefix, **input_kwargs)
        generation_output = self.model.generate(**gen_kwargs)
        outputs = generation_output.tolist()[0][prompt_length:]
        response = self.tokenizer.decode(outputs, skip_special_tokens=True)
        response_length = len(outputs)
        return response, (prompt_length, response_length)

    @torch.inference_mode()
    def stream_chat(
        self, query: str, history: Optional[List[Tuple[str, str]]] = None, prefix: Optional[str] = None, **input_kwargs
    ) -> Generator[str, None, None]:
        gen_kwargs, _ = self.process_args(query, history, prefix, **input_kwargs)
        streamer = TextIteratorStreamer(self.tokenizer, timeout=60.0, skip_prompt=True, skip_special_tokens=True)
        gen_kwargs["streamer"] = streamer

        thread = Thread(target=self.model.generate, kwargs=gen_kwargs)
        thread.start()

        for new_text in streamer:
            yield new_text
