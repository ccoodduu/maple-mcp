import ctypes
import os
import sys

MAPLE_ROOT = os.environ.get("MAPLE", r"C:\Program Files\Maple 2025")
os.environ["MAPLE"] = MAPLE_ROOT

_maple_bin = os.path.join(MAPLE_ROOT, "bin.X86_64_WINDOWS")
if _maple_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _maple_bin + os.pathsep + os.environ.get("PATH", "")

# Python 3.8+ on Windows requires os.add_dll_directory() for dependent DLL
# resolution — PATH changes alone are no longer sufficient.
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(_maple_bin)


class MCallBackVectorDesc(ctypes.Structure):
    _fields_ = [
        ("textCallBack", ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)),
        ("errorCallBack", ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int64, ctypes.c_char_p)),
        ("statusCallBack", ctypes.c_void_p),
        ("readLineCallBack", ctypes.c_void_p),
        ("redirectCallBack", ctypes.c_void_p),
        ("streamCallBack", ctypes.c_void_p),
        ("queryInterrupt", ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)),
        ("callBackCallBack", ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_char_p)),
    ]


def _find_maplec_dll():
    if sys.platform.startswith("win32"):
        target = "maplec.dll"
    elif sys.platform.startswith("linux"):
        target = "libmaplec.so"
    elif sys.platform.startswith("darwin"):
        target = "libmaplec.dylib"
    else:
        target = "maplec.dll"

    for root, _, files in os.walk(os.path.join(MAPLE_ROOT, "bin.X86_64_WINDOWS")):
        if target in files:
            return os.path.join(root, target)

    for entry in os.listdir(MAPLE_ROOT):
        full = os.path.join(MAPLE_ROOT, entry)
        if os.path.isdir(full) and entry.startswith("bin"):
            for root, _, files in os.walk(full):
                if target in files:
                    return os.path.join(root, target)
    return None


def _load_maplec(dll_path):
    maplec = ctypes.CDLL(dll_path)
    KV = ctypes.c_void_p
    ALGEB = ctypes.c_void_p

    maplec.StartMaple.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(MCallBackVectorDesc), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
    maplec.StartMaple.restype = KV
    maplec.StopMaple.argtypes = [KV]
    maplec.StopMaple.restype = ctypes.c_void_p
    maplec.EvalMapleStatement.argtypes = [KV, ctypes.c_char_p]
    maplec.EvalMapleStatement.restype = ALGEB
    maplec.MapleALGEB_SPrintf1.argtypes = [KV, ctypes.c_char_p, ALGEB]
    maplec.MapleALGEB_SPrintf1.restype = ALGEB
    maplec.MapleToString.argtypes = [KV, ALGEB]
    maplec.MapleToString.restype = ctypes.c_char_p
    maplec.IsMapleString.argtypes = [KV, ALGEB]
    maplec.IsMapleString.restype = ctypes.c_bool

    return maplec


class MapleEngine:
    def __init__(self):
        self._maplec = None
        self._kv = None
        self._text_output = []
        self._error_output = []
        self._cb_refs = []
        self._ts2str_defined = False

    def _ensure_kernel(self):
        if self._kv is not None:
            return

        dll_path = _find_maplec_dll()
        if dll_path is None:
            raise FileNotFoundError(
                f"Could not find maplec DLL in {MAPLE_ROOT}. "
                "Set the MAPLE environment variable to your Maple installation root."
            )

        self._maplec = _load_maplec(dll_path)

        text_output = self._text_output

        @ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)
        def text_cb(data, tag, output):
            text_output.append(output.decode("utf-8", errors="replace"))

        error_output = self._error_output

        @ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int64, ctypes.c_char_p)
        def error_cb(data, offset, msg):
            error_output.append(msg.decode("utf-8", errors="replace"))

        @ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)
        def query_interrupt(data):
            return False

        @ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_char_p)
        def callback_cb(data, output):
            return None

        self._cb_refs = [text_cb, error_cb, query_interrupt, callback_cb]

        mcbv = MCallBackVectorDesc(
            text_cb, error_cb, 0, 0, 0, 0, query_interrupt, callback_cb,
        )
        self._mcbv = ctypes.pointer(mcbv)

        err_buf = ctypes.create_string_buffer(2048)
        self._kv = self._maplec.StartMaple(0, ctypes.c_char_p(), self._mcbv, 0, 0, err_buf)

        if not self._kv:
            err_msg = err_buf.value.decode("utf-8", errors="replace")
            raise RuntimeError(f"Failed to start Maple kernel: {err_msg}")

        self._text_output.clear()
        self._error_output.clear()
        self._maplec.EvalMapleStatement(self._kv, b"interface(prettyprint=0, helpbrowser=false):")
        self._text_output.clear()
        self._error_output.clear()

    def _algeb_to_string(self, algeb):
        if not algeb:
            return None
        if self._maplec.IsMapleString(self._kv, algeb):
            raw = self._maplec.MapleToString(self._kv, algeb)
            if raw:
                return raw.decode("utf-8", errors="replace")
        fmt = self._maplec.MapleALGEB_SPrintf1(self._kv, b"%a", algeb)
        if fmt:
            raw = self._maplec.MapleToString(self._kv, fmt)
            if raw:
                return raw.decode("utf-8", errors="replace")
        return None

    def execute(self, statement: str) -> str:
        self._ensure_kernel()
        self._text_output.clear()
        self._error_output.clear()

        statement = statement.strip()
        if not statement.endswith(";") and not statement.endswith(":"):
            statement += ";"

        try:
            result = self._maplec.EvalMapleStatement(self._kv, statement.encode("utf-8"))
        except Exception as e:
            return f"Error: {e}"

        if self._error_output:
            return "Error: " + "".join(self._error_output).strip()

        text = "".join(self._text_output).strip()

        if text:
            return text

        result_str = self._algeb_to_string(result)
        if result_str:
            return result_str

        return "(no output)"

    def encode_equation(self, expr: str, background: str | None = None) -> tuple[str, str]:
        import re

        expr = expr.strip().rstrip(";:")
        expr = self._preprocess_notation(expr)

        # Chained / leading relations (a=b=c, 0<=x<=1, "=4*a*b"): split at
        # top-level relational operators and join the typeset operands. This
        # only triggers for chains (>=2 operators) or a leading relation, so
        # ordinary single-relation equations keep their existing code path.
        _operands, _rel_ents = self._split_relations(expr)
        if len(_rel_ents) >= 2 or (_rel_ents and not _operands[0].strip()):
            return self._encode_relation_chain(_operands, _rel_ents)

        # := assignments: encode LHS and RHS separately, join with &coloneq;
        if ':=' in expr:
            lhs, rhs = expr.split(':=', 1)
            lhs, rhs = lhs.strip(), rhs.strip()
            # Encode as: mrow(LHS_typesetting, mo("&coloneq;"), RHS_typesetting)
            raw = self._execute_clean(
                f'local ts, lhs_ts, rhs_ts:\n'
                f'lhs_ts := InertForm:-Typeset(InertForm:-Parse("{lhs}"), inert=false):\n'
                f'lhs_ts := subsindets(lhs_ts, specfunc(Typesetting:-mcomplete), proc(x) op(1,x) end proc):\n'
                f'lhs_ts := subsindets(lhs_ts, specfunc(Typesetting:-_Hold), proc(x) NULL end proc):\n'
                f'rhs_ts := InertForm:-Typeset(InertForm:-Parse("{rhs}"), inert=false):\n'
                f'rhs_ts := subsindets(rhs_ts, specfunc(Typesetting:-mcomplete), proc(x) op(1,x) end proc):\n'
                f'rhs_ts := subsindets(rhs_ts, specfunc(Typesetting:-_Hold), proc(x) NULL end proc):\n'
                f'ts := Typesetting:-mrow(lhs_ts, Typesetting:-mo("&coloneq;"), rhs_ts):\n'
                f'printf("%s", op(-1, DocumentTools:-Layout:-Equation(ts,'
                f' style=TwoDimInput, executable=true)));\n'
            )
            if 'Error' in raw or 'error' in raw:
                self._last_encode_error = raw.strip()
                return '', ''
            content_b64 = ''.join(raw.split())
            return content_b64, content_b64

        # Convert underscore subscripts to Maple bracket notation: c_p → c[p]
        expr = re.sub(r'\b([a-zA-Z])_([a-zA-Z0-9]+)\b', r'\1[\2]', expr)

        def _greek_subs_code():
            """Generate Maple subs() to convert DeltaX → ΔX variable names."""
            import re as _re
            names = set()
            for m in _re.finditer(r'\bDelta([A-Z])\b', expr):
                full = m.group(0)    # e.g. "DeltaT"
                letter = m.group(1)  # e.g. "T"
                names.add((full, f"&Delta;{letter}"))
            if not names:
                return ''
            subs_parts = ', '.join(
                f'Typesetting:-mi("{old}") = Typesetting:-mi("{new}")'
                for old, new in names
            )
            return f'ts := subs({subs_parts}, ts):\n'

        has_units = "Unit(" in expr

        UNIT_DISPLAY = {
            "Omega": "&Omega;",
            "degC": "&deg;C",
            "degF": "&deg;F",
        }

        if has_units:
            # Replace each Unit(...) with a placeholder, build unit TS for each
            placeholders = {}
            ph_counter = [0]
            def _replace_unit(m):
                ph_name = f'UPH{ph_counter[0]}'
                ph_counter[0] += 1
                unit_inner = m.group(1)
                placeholders[ph_name] = self._build_compound_unit_ts(unit_inner, UNIT_DISPLAY)
                return ph_name
            # Match Unit(...) with balanced parentheses
            def _find_units(s):
                result = s
                while 'Unit(' in result:
                    idx = result.find('Unit(')
                    depth, end = 0, idx + 5
                    for j in range(idx + 5, len(result)):
                        if result[j] == '(': depth += 1
                        elif result[j] == ')':
                            if depth == 0: end = j; break
                            depth -= 1
                    inner = result[idx+5:end]
                    m_obj = type('M', (), {'group': lambda self, i=0, v=inner: v})()
                    ph = _replace_unit(m_obj)
                    result = result[:idx] + ph + result[end+1:]
                return result
            expr_with_ph = _find_units(expr)

            # Build Maple code: InertForm on placeholders, then substitute unit TS
            locals_decl = ', '.join(['ts'] + [f'{k}_ts' for k in placeholders])
            assign_units = '\n'.join(
                f'{k}_ts := {v}:' for k, v in placeholders.items()
            )
            subs_code = 'ts := subsindets(ts, specfunc(Typesetting:-mi), proc(x) '
            for k in placeholders:
                subs_code += f'if op(1,x) = "{k}" then {k}_ts el'
            subs_code += 'se x end if end proc):'

            raw = self._execute_clean(
                f'local {locals_decl}:\n'
                f'ts := InertForm:-Typeset(InertForm:-Parse("{expr_with_ph}"), inert=false):\n'
                f'ts := subsindets(ts, specfunc(Typesetting:-mcomplete), proc(x) op(1,x) end proc):\n'
                f'ts := subsindets(ts, specfunc(Typesetting:-_Hold), proc(x) NULL end proc):\n'
                f'{assign_units}\n'
                f'{subs_code}\n'
                f'ts := subsindets(ts, specfunc(Typesetting:-mrow), proc(x) '
                f'local i, ops, new_ops; ops := [op(x)]; new_ops := []; '
                f'for i from 1 to nops(ops) do '
                f'if i < nops(ops) and type(ops[i], specfunc(Typesetting:-mo)) '
                f'and op(1,ops[i]) = "&sdot;" '
                f'and type(ops[i+1], specfunc(Typesetting:-mfenced)) then '
                f'new_ops := [op(new_ops), Typesetting:-mo("&InvisibleTimes;")] '
                f'else new_ops := [op(new_ops), ops[i]] end if end do; '
                f'Typesetting:-mrow(op(new_ops)) end proc):\n'
                f'{_greek_subs_code()}'
                f'printf("%s", op(-1, DocumentTools:-Layout:-Equation(ts,'
                f' style=TwoDimInput, executable=false)));\n'
            )
        else:
            raw = self._execute_clean(
                f'local ts:\n'
                f'ts := InertForm:-Typeset(InertForm:-Parse("{expr}"), inert=false):\n'
                f'ts := subsindets(ts, specfunc(Typesetting:-mcomplete), proc(x) op(1,x) end proc):\n'
                f'ts := subsindets(ts, specfunc(Typesetting:-_Hold), proc(x) NULL end proc):\n'
                f'{self._notation_fixup("ts")}'
                f'{_greek_subs_code()}'
                f'printf("%s", op(-1, DocumentTools:-Layout:-Equation(ts,'
                f' style=TwoDimInput, executable=false)));\n'
            )

        if 'Error' in raw or 'error' in raw:
            self._last_encode_error = raw.strip()
            return '', ''
        content_b64 = ''.join(raw.split())

        # Inject background color into Typesetting elements
        if background and content_b64:
            import base64
            decoded = base64.b64decode(content_b64).decode('latin-1')
            tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "maple_bg.m")
            with open(tmp, 'wb') as f:
                f.write(decoded.encode('latin-1'))
            tmp_fwd = tmp.replace(chr(92), '/')

            bg_raw = self._execute_clean(
                f'local ts, bg_ts:\n'
                f'ts := op(sscanf(FileTools:-Text:-ReadFile("{tmp_fwd}"), "%m")):\n'
                f'bg_ts := subsindets(ts, specfunc(Typesetting:-mi), '
                f'  proc(x) Typesetting:-mi(op(x), background="{background}", opaque="true") end proc):\n'
                f'bg_ts := subsindets(bg_ts, specfunc(Typesetting:-mn), '
                f'  proc(x) Typesetting:-mn(op(x), background="{background}", opaque="true") end proc):\n'
                f'bg_ts := subsindets(bg_ts, specfunc(Typesetting:-mo), '
                f'  proc(x) Typesetting:-mo(op(x), background="{background}", opaque="true") end proc):\n'
                f'printf("%s", op(-1, DocumentTools:-Layout:-Equation(bg_ts,'
                f' style=TwoDimInput, executable=false)));\n'
            )
            try:
                os.unlink(tmp)
            except OSError:
                pass

            bg_b64 = ''.join(bg_raw.split())
            if bg_b64:
                content_b64 = bg_b64

        display_b64 = content_b64
        return display_b64, content_b64

    def _build_compound_unit_ts(self, unit_inner: str, display_map: dict) -> str:
        """Build Typesetting mfenced for compound unit like 'J'/('kg'*'degC')."""
        import re

        # Strip quotes from unit names
        clean = unit_inner.replace("'", "")

        # Split into numerator/denominator
        if '/' in clean:
            parts = clean.split('/', 1)
            num_str = parts[0].strip('()')
            den_str = parts[1].strip('()')
        else:
            num_str = clean
            den_str = None

        def _unit_mi(name):
            if '^' in name:
                base, exp = name.split('^', 1)
                base_display = display_map.get(base, base)
                return (
                    f'Typesetting:-msup('
                    f'Typesetting:-mi("{base_display}"),'
                    f'Typesetting:-mn("{exp}"))'
                )
            display = display_map.get(name, name)
            return f'Typesetting:-mi("{display}")'

        def _build_product(s):
            names = [n.strip() for n in s.split('*')]
            if len(names) == 1:
                return _unit_mi(names[0])
            items = []
            for i, n in enumerate(names):
                if i > 0:
                    items.append('Typesetting:-mo("&InvisibleTimes;")')
                items.append(_unit_mi(n))
            return f'Typesetting:-mrow({", ".join(items)})'

        num_ts = _build_product(num_str)

        if den_str:
            den_ts = _build_product(den_str)
            frac_ts = f'Typesetting:-mfrac({num_ts},{den_ts})'
        else:
            frac_ts = num_ts

        # Match Maple's native format: content first, then open/close, msemantics last
        return (
            f'Typesetting:-mfenced('
            f'{frac_ts},'
            f'open = "&lobrk;", close = "&robrk;",'
            f'Typesetting:-msemantics = "Unit")'
        )

    @staticmethod
    def _maple_str(s: str) -> str:
        """Escape a Python string into a Maple double-quoted string literal."""
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

    @staticmethod
    def _preprocess_notation(expr: str) -> str:
        """Make a few human notations parseable by InertForm:-Parse:
          '+-' / '+/-'  -> the &pm neutral operator (a parseable binary op)
          f'(x)         -> fPRIMESENT(x)
        Both are turned back into proper Typesetting by _notation_fixup().
        """
        expr = expr.replace('+/-', ' &pm ').replace('+-', ' &pm ')
        # Mark derivative primes WITHOUT mangling Maple single-quoted strings
        # such as Unit('Omega') (whose closing quote also follows a letter).
        out, in_quote = [], False
        for ch in expr:
            if ch == "'":
                if in_quote:
                    in_quote = False
                    out.append(ch)
                elif out and (out[-1].isalnum() or out[-1] == ']'):
                    out.append('PRIMESENT')
                else:
                    in_quote = True
                    out.append(ch)
            else:
                out.append(ch)
        return ''.join(out)

    @staticmethod
    def _notation_fixup(var: str) -> str:
        """Maple subsindets snippet: the &pm operator -> a PlusMinus sign, and
        any name ending in PRIMESENT -> a prime superscript (f -> f')."""
        return (
            f'{var} := subsindets({var}, specfunc(Typesetting:-mo), proc(x) '
            f'if StringTools:-Search("pm", op(1,x)) > 0 then Typesetting:-mo("&PlusMinus;") '
            f'else x end if end proc):\n'
            f'{var} := subsindets({var}, specfunc(Typesetting:-mi), proc(x) local s; s := op(1,x); '
            f'if type(s, string) and StringTools:-IsSuffix("PRIMESENT", s) then '
            f'Typesetting:-msup(Typesetting:-mi(s[1 .. -10]), Typesetting:-mo("&prime;")) '
            f'else x end if end proc):\n'
        )

    @staticmethod
    def _split_relations(expr: str):
        """Split expr at TOP-LEVEL relational operators (longest-match first).

        Returns (operands, operator_entities). '=' inside (), [], {} or ranges
        is not split (it stays inside an operand), and the '>' of an arrow '->'
        is not treated as a relation.
        """
        ops = [(':=', '&coloneq;'), ('<=', '&le;'), ('>=', '&ge;'),
               ('<>', '&ne;'), ('=', '='), ('<', '&lt;'), ('>', '&gt;')]
        operands, operator_ents = [], []
        cur, depth, i, n = '', 0, 0, len(expr)
        while i < n:
            c = expr[i]
            if c in '([{':
                depth += 1; cur += c; i += 1; continue
            if c in ')]}':
                depth -= 1; cur += c; i += 1; continue
            if depth == 0:
                matched = next(((t, e) for t, e in ops if expr[i:i + len(t)] == t), None)
                if matched:
                    tok, ent = matched
                    if tok == '>' and cur.rstrip().endswith('-'):  # arrow '->'
                        cur += c; i += 1; continue
                    operands.append(cur); operator_ents.append(ent)
                    cur = ''; i += len(tok); continue
            cur += c; i += 1
        operands.append(cur)
        return operands, operator_ents

    def _encode_relation_chain(self, operands, operator_ents):
        """Typeset each operand and join them with the relation operators as an
        mrow. Used for chained/leading relations the Maple parser rejects."""
        import re
        ts_vars, lines = [], []
        for idx, operand in enumerate(operands):
            operand = operand.strip()
            if not operand:
                ts_vars.append(None)
                continue
            operand = re.sub(r'\b([a-zA-Z])_([a-zA-Z0-9]+)\b', r'\1[\2]', operand)
            v = f'o{idx}_ts'
            lit = self._maple_str(operand)
            lines.append(f'{v} := InertForm:-Typeset(InertForm:-Parse({lit}), inert=false):')
            lines.append(f'{v} := subsindets({v}, specfunc(Typesetting:-mcomplete), proc(x) op(1,x) end proc):')
            lines.append(f'{v} := subsindets({v}, specfunc(Typesetting:-_Hold), proc(x) NULL end proc):')
            ts_vars.append(v)
        if not any(ts_vars):
            self._last_encode_error = 'empty relation chain'
            return '', ''
        mrow_args = []
        for idx, v in enumerate(ts_vars):
            if idx > 0:
                mrow_args.append(f'Typesetting:-mo("{operator_ents[idx - 1]}")')
            if v is not None:
                mrow_args.append(v)
        decl = ', '.join(['ts'] + [v for v in ts_vars if v])
        body = '\n'.join(lines)
        mrow = ', '.join(mrow_args)
        raw = self._execute_clean(
            f'local {decl}:\n'
            f'{body}\n'
            f'ts := Typesetting:-mrow({mrow}):\n'
            f'{self._notation_fixup("ts")}'
            f'printf("%s", op(-1, DocumentTools:-Layout:-Equation(ts,'
            f' style=TwoDimInput, executable=false)));\n'
        )
        if 'Error' in raw or 'error' in raw:
            self._last_encode_error = raw.strip()
            return '', ''
        content_b64 = ''.join(raw.split())
        return content_b64, content_b64

    @staticmethod
    def _execute_clean(statement: str) -> str:
        """Execute a Maple statement in a clean subprocess (no user variables)."""
        import subprocess
        cmaple = os.path.join(MAPLE_ROOT, "bin.X86_64_WINDOWS", "cmaple.exe")
        try:
            result = subprocess.run(
                [cmaple, "-q"],
                input=statement + "\nquit;\n",
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15
            )
            # Clean output: join lines, strip whitespace
            lines = [l.strip() for l in result.stdout.strip().split('\n')
                     if l.strip() and not l.strip().startswith('>')]
            return "\n".join(lines)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def _ensure_ts2str(self):
        if self._ts2str_defined:
            return
        self._ensure_kernel()
        self.execute('''
TS2Str := proc(e)
    local i, s, o, t;
    if type(e, string) then
        if member(e, {"true","false","bold","italic","normal","none","bold-italic"}) then return "" end if;
        return e
    end if;
    if not type(e, function) then return "" end if;
    t := op(0, e);
    s := "";
    if type(e, specfunc(Typesetting:-mcomplete)) then
        s := procname(op(1, e))
    elif type(e, specfunc(Typesetting:-mfrac)) then
        s := cat("(", procname(op(1,e)), ")/(", procname(op(2,e)), ")")
    elif type(e, specfunc(Typesetting:-msup)) then
        s := cat(procname(op(1,e)), "^", procname(op(2,e)))
    elif type(e, specfunc(Typesetting:-msub)) then
        s := cat(procname(op(1,e)), "_", procname(op(2,e)))
    elif type(e, specfunc(Typesetting:-mfenced)) then
        if has(e, "&lobrk;") then
            s := cat("[[", procname(op(1,e)), "]]")
        else
            s := cat("(", procname(op(1,e)), ")")
        end if
    elif type(e, specfunc(Typesetting:-msqrt)) then
        s := cat("sqrt(", procname(op(1,e)), ")")
    else
        for i from 1 to nops(e) do
            o := op(i, e);
            if type(o, equation) then next end if;
            s := cat(s, procname(o))
        end do
    end if;
    s
end proc:
''')
        # Warm up: first call to TS2Str with Typesetting module fails
        # due to lazy module loading. Run a dummy call to force initialization.
        self.execute('TS2Str(Typesetting:-mi("x")):')
        self._ts2str_defined = True

    def decode_equation(self, b64_data: str) -> str:
        import base64
        self._ensure_ts2str()

        decoded = base64.b64decode(b64_data)
        tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "maple_eq.m")
        with open(tmp, "wb") as f:
            f.write(decoded)
        tmp_fwd = tmp.replace(chr(92), "/")

        result = self.execute(
            f'printf("%s", TS2Str(op(sscanf(FileTools:-Text:-ReadFile("{tmp_fwd}"), "%m"))))'
        )
        if "Error" in result or "Typesetting" in result:
            result = self.execute(
                f'sprintf("%a", op(sscanf(FileTools:-Text:-ReadFile("{tmp_fwd}"), "%m")))'
            )

        try:
            os.unlink(tmp)
        except OSError:
            pass

        if "Error" in result:
            return ""

        import html
        result = result.strip('"')
        # Maple custom entities (not in HTML standard)
        result = result.replace('&uminus0;', '-')
        result = result.replace('&it;', '*')
        result = html.unescape(result)
        # Remove invisible Unicode characters
        result = result.replace('\u2061', '')   # ApplyFunction
        result = result.replace('\u2062', '*')  # InvisibleTimes → *
        result = result.replace('\u2254', ':=')  # coloneq → :=
        result = result.replace('\u2146', '')   # DifferentialD
        result = result.replace('\u2145', '')   # DoubleStruckCapitalD
        result = result.replace('  ', ' ')
        # Normalize visible operator glyphs the encoder cannot re-parse
        for _g, _a in (('⋅', '*'), ('−', '-'), ('≤', '<='), ('≥', '>='), ('≠', '<>')):
            result = result.replace(_g, _a)

        # Detect highlight color in the raw Typesetting data
        self._last_eq_background = None
        if b'background' in decoded:
            import re as _re
            bg_match = _re.search(r'background.*?\[(\d+,\d+,\d+)\]', decoded.decode('ascii', errors='replace'))
            if bg_match:
                self._last_eq_background = bg_match.group(1)

        return result.strip()

    def get_help(self, topic: str) -> str:
        return self.execute(f"help({topic})")

    def stop(self):
        if self._kv is not None and self._maplec is not None:
            try:
                self._maplec.StopMaple(self._kv)
            except Exception:
                pass
            self._kv = None


engine = MapleEngine()
