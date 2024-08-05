import time
from typing import Union, List
from persons.asynchronous_persons.inner_scheduler_asynchronous_person import \
    InnerSchedulerAsynchronousPerson
from session_rooms.session_room import ChatEntry
import logging

log = logging.getLogger(__name__)

PASS_TURN_TOKEN = "<pass>"
USE_TURN_TOKEN = "<speak>"


class FirstGeneratesThenDecides(InnerSchedulerAsynchronousPerson):
    PERSON_TYPE = "first_generates_then_decides"

    def __init__(self, background_story: str, name: str,
                 pass_turn_token: str = PASS_TURN_TOKEN,
                 use_turn_token: str = USE_TURN_TOKEN, *args, **kwargs):
        super().__init__(background_story=background_story, name=name, *args, **kwargs)
        self.pass_turn_token = pass_turn_token
        self.use_turn_token = use_turn_token

    def _create_prompt_skeleton(self, experiment_scenario: str, chat_list: List[ChatEntry],
                                task: str) -> str:
        output = ("### Instruction: \n"
                  f"Your name is {self.name}. \n"
                  f"This is your background story: {self.background_story}.\n"
                  f"The following is {experiment_scenario}. "
                  f"Based on the following chat history [with timestamps], "
                  f"{task}\n"
                  f"The current time is: [{time.strftime('%H:%M:%S')}]\n\n"
                  "### Input: (Chat History)\n")
        if not chat_list:
            output += "(No chat message was added yet)\n"
        else:
            for chat_entry in chat_list:
                output += f"[{chat_entry.time}] {chat_entry.entity.name}: {chat_entry.answer}\n"
        output += "### Response:"
        return output

    def create_context_for_scheduler(self, experiment_scenario: str, chat_list: List[ChatEntry],
                                     *potential_answer) -> str:
        """
        Creates the prompt used by the inner scheduler to decide whether to generate an answer.
        (args must be the potential
        """
        task = (f"decide whether to pass the current turn without adding to the conversation "
                f"using '{self.pass_turn_token}', "
                f"or to use your turn to add the following potential message using "
                f"'{self.use_turn_token}'. The potential message: '{potential_answer}'. "
                f"Output only '{self.pass_turn_token}' or '{self.use_turn_token}'."
                f"Choose {self.use_turn_token} only if it's a proper timing!\n"
                # f"Here is an example:\n"
                # f"(12:36:31 - David chose {self.use_turn_token})\n"
                # f"[12:36:31] David: Chasing clouds, with dreams so clear,\n"
                # f"(12:39:45 - John chose {self.pass_turn_token})\n"
                # f"(12:40:53 - David chose {self.use_turn_token})\n"
                # f"[12:40:53] David: Dreams dance, in minds so dear.\n"
                # f"(12:42:04 - John chose {self.use_turn_token})\n"
                # f"[12:42:04] John: Beautiful imagery, it reminds me of few things,\n"
                # f"(12:43:16 - David chose {self.pass_turn_token})\n"
                # f"(12:44:31 - John chose {self.use_turn_token})\n"
                # f"[12:44:31] John: like flying in a dream, or cotton candy clouds."
                )
        return self._create_prompt_skeleton(experiment_scenario, chat_list, task)

    def should_generate_answer(self, scheduler_prompt: str) -> bool:
        """
        Decides whether to output the generated potential answer, using self.inner_scheduler_model.
        """
        scheduling_decision = self.inner_scheduler_model.generate(scheduler_prompt)
        scheduling_decision = scheduling_decision.split("### Response:")[1]
        scheduling_decision = scheduling_decision.strip().split("</s>")[0].split("\n")[0]
        scheduling_decision = scheduling_decision.removeprefix(f"{self.name}: ")
        time_and_name_prefix = f"] {self.name}: "
        if time_and_name_prefix in scheduling_decision:
            scheduling_decision = scheduling_decision.split(time_and_name_prefix)[1]
        return bool(scheduling_decision.strip()) and \
            (self.generation_model.generate_without_special_tokens
             or self.pass_turn_token not in scheduling_decision)

    def create_prompt(self, experiment_scenario: str, chat_list: List[ChatEntry]) -> str:
        """Creates the prompt for the generation model,
        once the inner scheduler has decided it should"""
        task = "add your message to the conversation. Try to keep your reply shorter than 30 words."
        return self._create_prompt_skeleton(experiment_scenario, chat_list, task)

    def generate_answer(self, experiment_scenario: str, chat_list: List[ChatEntry]
                        ) -> Union[ChatEntry, None]:
        prompt = self.create_prompt(experiment_scenario, chat_list)
        potential_answer = self.generation_model.generate(prompt)
        potential_answer = potential_answer.split("### Response:")[1]
        potential_answer = potential_answer.strip().split("</s>")[0].split("\n")[0]
        potential_answer = potential_answer.removeprefix(f"{self.name}: ")
        time_and_name_prefix = f"] {self.name}: "
        if time_and_name_prefix in potential_answer:
            potential_answer = potential_answer.split(time_and_name_prefix)[1]
        scheduler_prompt = self.create_context_for_scheduler(experiment_scenario, chat_list,
                                                             potential_answer)
        if self.should_generate_answer(scheduler_prompt):
            log.info("Model chose to generate!")
            current_time = time.strftime("%H:%M:%S")
            return ChatEntry(entity=self, prompt=prompt, answer=potential_answer, time=current_time)
        else:
            log.info("Model chose not to generate...")
            return None
