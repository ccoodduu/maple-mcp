"""Round-trip tests: write markup → encode → decode → same markup."""
import pytest


class TestEquationRoundTrip:
    """Equation encode → decode should preserve key elements."""

    @pytest.mark.parametrize("expr", [
        "x^2 + 3*x - 4",
        "m = 200",
        "Int(x^2, x = 0..3)",
        "solve(x^2 - 1, x)",
        "f(x) = cos(x)",
        "(a)/(b)",
        "3*4",
        "Int(x^2, x = 0..3) = 9",
        "solve(x^2-1=0, x)",
    ])
    def test_basic_equation(self, engine, expr):
        _, b64 = engine.encode_equation(expr)
        assert b64, f"Encoding failed for: {expr}"
        decoded = engine.decode_equation(b64)
        assert decoded, f"Decoding failed for: {expr}"

    @pytest.mark.parametrize("expr,expected_fragment", [
        ("200*Unit('kg')", "[[kg]]"),
        ("m = 200*Unit('kg')", "[[kg]]"),
        ("1000*Unit('kg'/'m'^3)", "[[(kg)/(m^3)]]"),
        ("4180*Unit('J'/('kg'*'degC'))", "[[(J)/(kg"),
        ("m = 1000*Unit('kg'/'m'^3)*0.2*Unit('m'^3)", "[["),
    ])
    def test_unit_round_trip(self, engine, expr, expected_fragment):
        _, b64 = engine.encode_equation(expr)
        assert b64, f"Encoding failed for: {expr}"
        decoded = engine.decode_equation(b64)
        assert decoded, f"Decoding failed for: {expr}"
        assert expected_fragment in decoded, (
            f"Expected '{expected_fragment}' in decoded '{decoded}' for: {expr}"
        )

    @pytest.mark.parametrize("expr,expected", [
        ("DeltaT = 45", "ΔT"),
        ("Q = m*c*DeltaT", "ΔT"),
        ("DeltaP + DeltaV", "ΔP"),
    ])
    def test_greek_delta(self, engine, expr, expected):
        _, b64 = engine.encode_equation(expr)
        assert b64, f"Encoding failed for: {expr}"
        decoded = engine.decode_equation(b64)
        assert expected in decoded, (
            f"Expected '{expected}' in decoded '{decoded}' for: {expr}"
        )

    def test_assignment_shows_variable(self, engine):
        """':=' should preserve variable name with coloneq operator."""
        _, b64 = engine.encode_equation("m := 200")
        decoded = engine.decode_equation(b64)
        assert "m" in decoded, f"Variable name lost: {decoded}"
        assert "200" in decoded, f"Value lost: {decoded}"
        assert "≔" in decoded or ":=" in decoded, f"Assignment operator lost: {decoded}"


class TestUnitSyntaxNormalization:
    """[[unit]] syntax should work with and without * before it."""

    @pytest.mark.parametrize("expr", [
        "1000 [[kg/m^3]]",
        "1000*[[kg/m^3]]",
        "200 [[kg]]",
        "200*[[kg]]",
    ])
    def test_space_and_star_both_work(self, engine, expr):
        from maple_mcp.document import _replace_units_in_expr
        replaced = _replace_units_in_expr(expr)
        assert "Unit(" in replaced
        assert "*Unit(" in replaced  # space normalized to *

        _, b64 = engine.encode_equation(replaced)
        assert b64, f"Encoding failed for: {expr}"


class TestErrorRejection:
    """Invalid expressions should raise ValueError, not produce corrupt XML."""

    def test_maple_syntax_error(self, engine):
        from maple_mcp.document import _equation_xml
        with pytest.raises(ValueError, match="encoding failed"):
            _equation_xml("totally broken !!!", executable=False)

    def test_maple_error_message_included(self, engine):
        from maple_mcp.document import _equation_xml
        with pytest.raises(ValueError, match="Maple error"):
            _equation_xml("1 + + 2", executable=False)


class TestChainedRelations:
    """Chained/leading relations (worked-calc notation) must encode and the
    decoded form must preserve the chain literally (no evaluation)."""

    @pytest.mark.parametrize("expr,fragments", [
        ("a = b = c", ["a", "b", "c"]),
        ("d = 25 + 24 = 49", ["25", "49"]),
        ("0 <= x <= 1", ["x"]),
        ("F(3) = 3^3/3 = 27/3 = 9", ["27", "9"]),
        ("x[1] = (5 + 7)/4 = 3", ["3"]),
    ])
    def test_chain_encodes_and_preserves(self, engine, expr, fragments):
        _, b64 = engine.encode_equation(expr)
        assert b64, f"Chained relation failed to encode: {expr}"
        decoded = engine.decode_equation(b64)
        for frag in fragments:
            assert frag in decoded, f"Lost '{frag}' in decoded '{decoded}' for: {expr}"

    def test_chain_not_evaluated(self, engine):
        """25 + 24 must stay literal, not collapse to 49."""
        _, b64 = engine.encode_equation("d = 25 + 24 = 49")
        decoded = engine.decode_equation(b64)
        assert "25" in decoded and "24" in decoded, f"Chain was evaluated: {decoded}"


class TestOperationArrow:
    """{{expr => op}} renders input ──op──▶ computed-result (context-panel style).
    The result is computed by the kernel, so encoding must succeed end-to-end."""

    @pytest.mark.parametrize("expr", [
        "x^2-5*x+6 => factor",
        "(x^2-4)/(x-2) => simplify",
        "1/3+1/6 => evaluate",
        "x^2-4 => solve",
        "200*Unit('kg') => evaluate",
    ])
    def test_operation_encodes(self, engine, expr):
        _, b64 = engine.encode_equation(expr)
        assert b64, f"operation failed to encode: {expr}"

    def test_bad_operation_fails_loudly(self, engine):
        """An unknown operation must fail (empty b64), not emit garbage."""
        engine._last_encode_error = None
        _, b64 = engine.encode_equation("x^2 => bogusop")
        assert not b64
