"""FSM States для moderator бота."""

from aiogram.fsm.state import State, StatesGroup


class ModeratorStates(StatesGroup):
    waiting_user_lookup = State()