import conftest  # noqa: F401  (sys.path 設定)

from keiba_ai.analysis.bias import build_bias, parse_bias_text, prompt_bias


def test_parse_inner_and_front():
    b = parse_bias_text("内有利で前残り")
    assert b.inner > 0.5
    assert b.front > 0.5
    assert b.speed == 0.0


def test_parse_outside_closers():
    b = parse_bias_text("外差しが決まる馬場")
    assert b.inner < -0.5
    assert b.front < 0


def test_intensifier_applies_only_to_its_own_phrase():
    b = parse_bias_text("内有利で前残り、時計はかなり速い")
    assert b.speed == 1.0            # 「かなり」が掛かる
    assert 0.7 < b.inner < 0.9       # 掛からない
    assert 0.7 < b.front < 0.9


def test_weakener_reduces_magnitude():
    strong = parse_bias_text("内有利")
    weak = parse_bias_text("やや内有利")
    assert 0 < weak.inner < strong.inner


def test_tough_track_and_condition_override():
    b = parse_bias_text("時計がかかるタフな馬場、不良まで悪化")
    assert b.speed < -0.5
    assert b.condition_override == "不良"


def test_particles_are_tolerated():
    assert parse_bias_text("内は荒れている").inner < 0
    assert parse_bias_text("内が不利").inner < 0
    assert parse_bias_text("前が止まる").front < 0
    assert parse_bias_text("前が止まらない").front > 0


def test_empty_input_is_neutral():
    b = parse_bias_text("")
    assert b.is_empty
    assert "入力なし" in b.describe()


def test_numeric_override_wins():
    b = build_bias(text="内有利で前残り", inner=-0.9, speed=0.25)
    assert b.inner == -0.9
    assert b.speed == 0.25
    assert b.front > 0     # 指定していない軸は自然文の解釈が残る


def test_confidence_scales_strength():
    strong = build_bias(text="内有利で前残り", confidence=1.0)
    weak = build_bias(text="内有利で前残り", confidence=0.4)
    assert weak.strength < strong.strength


def test_prompt_bias_free_text():
    answers = iter(["外差し有利", "2"])
    b = prompt_bias(input_fn=lambda _: next(answers), output_fn=lambda *a: None)
    assert b.inner < 0
    assert b.confidence == 0.7


def test_prompt_bias_menu_mode():
    # 1問目で空欄 → 選択式。inner=5(内有利), front=1(差し), speed=3(標準), 馬場, 確信度
    answers = iter(["", "5", "1", "3", "重", "3"])
    b = prompt_bias(input_fn=lambda _: next(answers), output_fn=lambda *a: None)
    assert b.inner == 0.8
    assert b.front == -0.8
    assert b.speed == 0.0
    assert b.condition_override == "重"
    assert b.confidence == 1.0
