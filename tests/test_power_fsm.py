"""Tests for chatterbox/power/fsm.py -- pure logic, no hardware, fake-injected
backlight/amp/broadcast/halt (see chatterbox-powerd_spec_v0.1.md Sec4/Sec10 "FSM" test plan)."""
import pytest

from chatterbox.power.fsm import ACTIVE, DIM, DARK, DEEP, PowerFSM


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeBacklight:
    def __init__(self):
        self.on_calls = 0
        self.off_calls = 0
        self.brightness_calls = []

    def on(self):
        self.on_calls += 1

    def off(self):
        self.off_calls += 1

    def brightness(self, value):
        self.brightness_calls.append(value)


class FakeAmp:
    def __init__(self):
        self.set_calls = []
        self.watchdog_calls = []
        self.value = False

    def set(self, on):
        self.value = bool(on)
        self.set_calls.append(bool(on))

    def check_watchdog(self, now):
        self.watchdog_calls.append(now)


def make_cfg(t_dim_s=10, t_dark_s=20, t_deep_s=30, deep_manual_only=False,
             brightness_active=255, brightness_dim=60):
    return {
        "power": {
            "t_dim_s": t_dim_s,
            "t_dark_s": t_dark_s,
            "t_deep_s": t_deep_s,
            "deep_manual_only": deep_manual_only,
        },
        "display": {
            "brightness_active": brightness_active,
            "brightness_dim": brightness_dim,
        },
    }


def make_fsm(cfg=None, clock=None):
    clock = clock or FakeClock()
    backlight = FakeBacklight()
    amp = FakeAmp()
    broadcasts = []
    halts = []
    fsm = PowerFSM(
        cfg or make_cfg(), backlight, amp,
        broadcast_fn=broadcasts.append, halt_fn=lambda: halts.append(True),
        now_fn=clock,
    )
    return fsm, backlight, amp, broadcasts, halts, clock


def test_initial_state_is_active_with_entry_actions_run():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    assert fsm.state == ACTIVE
    assert backlight.on_calls == 1
    assert backlight.brightness_calls == [255]
    assert broadcasts == []  # construction is not a "transition"


def test_descends_through_all_thresholds_in_order():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()

    clock.advance(10)
    fsm.on_tick()
    assert fsm.state == DIM
    assert backlight.brightness_calls[-1] == 60
    assert broadcasts[-1] == {"type": "state", "value": DIM}

    clock.advance(10)  # idle = 20 -> hits t_dark_s
    fsm.on_tick()
    assert fsm.state == DARK
    assert backlight.off_calls == 1
    assert amp.set_calls[-1] is False
    assert broadcasts[-1] == {"type": "state", "value": DARK}

    clock.advance(10)  # idle = 30 -> hits t_deep_s
    fsm.on_tick()
    assert fsm.state == DEEP
    assert broadcasts[-1] == {"type": "state", "value": DEEP}
    assert halts == [True]


def test_long_idle_jumps_straight_to_deepest_satisfied_threshold():
    """A tick that finds idle time already past every threshold (e.g. daemon started up long
    after the last activity) goes straight to the deepest satisfied state in one hop, not
    DIM->DARK->DEEP one tick at a time."""
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    clock.advance(1000)
    fsm.on_tick()
    assert fsm.state == DEEP
    assert halts == [True]


def test_instant_ascent_on_activity_from_any_state():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    clock.advance(20)
    fsm.on_tick()
    assert fsm.state == DARK

    backlight_calls_before = len(backlight.brightness_calls)
    fsm.on_activity("evdev")
    assert fsm.state == ACTIVE
    assert backlight.brightness_calls[-1] == 255
    assert len(backlight.brightness_calls) == backlight_calls_before + 1
    assert broadcasts[-1] == {"type": "state", "value": ACTIVE}


def test_activity_while_already_active_does_not_retransition():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    fsm.on_activity("evdev")
    assert broadcasts == []  # no-op transition -> no broadcast, no re-run of entry actions
    assert backlight.on_calls == 1  # only the constructor's initial entry action


def test_put_away_goes_directly_to_deep_from_active():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    fsm.on_command("PUT_AWAY")
    assert fsm.state == DEEP
    assert halts == [True]
    assert broadcasts[-1] == {"type": "state", "value": DEEP}


def test_deep_manual_only_blocks_the_timer_but_not_put_away():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm(make_cfg(deep_manual_only=True))
    clock.advance(1000)
    fsm.on_tick()
    assert fsm.state == DARK  # capped -- never auto-reaches DEEP
    assert halts == []

    fsm.on_command("PUT_AWAY")
    assert fsm.state == DEEP
    assert halts == [True]


def test_t_deep_s_null_disables_deep_timer_entirely():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm(make_cfg(t_deep_s=None))
    clock.advance(100000)
    fsm.on_tick()
    assert fsm.state == DARK
    assert halts == []


def test_deep_is_terminal_tick_is_a_full_noop():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    fsm.on_command("PUT_AWAY")
    assert fsm.state == DEEP
    watchdog_calls_before = len(amp.watchdog_calls)
    broadcasts_before = len(broadcasts)

    fsm.on_tick()
    fsm.on_tick()

    assert len(amp.watchdog_calls) == watchdog_calls_before  # spec: tick returns before watchdog
    assert len(broadcasts) == broadcasts_before
    assert halts == [True]  # not re-invoked


def test_entry_actions_fire_exactly_once_per_actual_state_change_not_per_tick():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    brightness_calls_before = len(backlight.brightness_calls)

    # Idle stays below every threshold -- repeated ticks must not re-run entry actions.
    for _ in range(5):
        clock.advance(1)
        fsm.on_tick()

    assert fsm.state == ACTIVE
    assert len(backlight.brightness_calls) == brightness_calls_before
    assert broadcasts == []


def test_amp_watchdog_polled_every_tick_while_not_deep():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    for _ in range(3):
        clock.advance(1)
        fsm.on_tick()
    assert len(amp.watchdog_calls) == 3


@pytest.mark.parametrize("on,expected_state", [(True, "on"), (False, "off")])
def test_amp_on_off_commands_set_the_amp_and_ack(on, expected_state):
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    reply = fsm.on_command("AMP_ON" if on else "AMP_OFF")
    assert reply == ("amp_ack", expected_state)
    assert amp.value is on


def test_get_state_command():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm()
    assert fsm.on_command("GET_STATE") == ("state", ACTIVE)
    clock.advance(20)
    fsm.on_tick()
    assert fsm.on_command("GET_STATE") == ("state", DARK)


def test_reload_command_invokes_reload_fn():
    calls = []
    cfg = make_cfg()
    backlight = FakeBacklight()
    amp = FakeAmp()
    fsm = PowerFSM(cfg, backlight, amp, broadcast_fn=lambda p: None, halt_fn=lambda: None,
                   now_fn=FakeClock(), reload_fn=lambda: calls.append(True))
    assert fsm.on_command("RELOAD") is None
    assert calls == [True]


def test_set_config_swaps_thresholds_used_by_the_next_tick():
    fsm, backlight, amp, broadcasts, halts, clock = make_fsm(make_cfg(t_dim_s=5))
    clock.advance(5)
    fsm.on_tick()
    assert fsm.state == DIM

    fsm.on_activity()  # back to ACTIVE
    fsm.set_config(make_cfg(t_dim_s=1000))  # much longer dim threshold now
    clock.advance(5)
    fsm.on_tick()
    assert fsm.state == ACTIVE  # would have hit DIM under the old config
