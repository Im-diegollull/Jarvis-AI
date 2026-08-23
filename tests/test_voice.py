"""Sentence buffering decides how soon Jarvis starts talking. It gets tests."""

from unittest.mock import MagicMock

import pytest

from jarvis.voice.tts import Speaker, _spoken


@pytest.fixture
def speaker():
    """A Speaker with the network and the speakers stubbed out."""
    spk = Speaker(player=MagicMock(), client=MagicMock())
    spoken = []
    spk._enqueue = spoken.append          # capture instead of queueing
    spk.spoken = spoken
    return spk


def test_speaks_each_sentence_as_it_completes(speaker):
    for delta in ["Buenas tardes, señor. ", "Los sistemas están en orden. ", "Nada que "]:
        speaker.feed(delta)
    assert speaker.spoken == [
        "Buenas tardes, señor.",
        "Los sistemas están en orden.",
    ], "the trailing fragment must wait for more text"


def test_flush_speaks_the_remainder(speaker):
    speaker.feed("Todo listo. Nada pendiente")
    speaker.flush()
    assert speaker.spoken[-1] == "Nada pendiente"


def test_short_fragments_wait_instead_of_being_clipped(speaker):
    speaker.feed("Sí. ")
    assert speaker.spoken == [], "two-letter sentence would sound clipped on its own"
    speaker.feed("Ya he revisado su calendario de esta semana. ")
    assert speaker.spoken == ["Sí. Ya he revisado su calendario de esta semana."]


def test_newlines_break_sentences(speaker):
    speaker.feed("Primera línea larga de prueba\nSegunda línea larga de prueba\n")
    assert len(speaker.spoken) == 2


def test_interrupt_drops_pending_audio_and_the_buffer():
    spk = Speaker(player=MagicMock(), client=MagicMock())
    spk.feed("Una frase suficientemente larga para hablar. Y otra a medias")
    spk.interrupt()
    assert spk._buffer == ""
    spk.player.stop.assert_called_once()


def test_wait_does_not_return_while_audio_is_pending():
    spk = Speaker(player=MagicMock(), client=MagicMock())
    with spk._cond:
        spk._pending = 1
    assert spk.wait(timeout=0.05) is False, "wait must block while a sentence is queued"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("**Listo**, señor", "Listo, señor"),
        ("Mira https://uandes.instructure.com/x", "Mira un enlace"),
        ("- primero\n- segundo", "primero segundo"),
        ("## Título", "Título"),
        ("  espacios   raros  ", "espacios raros"),
    ],
)
def test_markdown_never_reaches_the_speakers(raw, expected):
    assert _spoken(raw) == expected
