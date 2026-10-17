import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cola


def enc(id_, repo="/r", tema=None, permitidos=("tests/**",)):
    return {"ruta": Path(f"/e/{id_}.md"),
            "cfg": {"id": id_, "proyecto": "p", "repo": repo, "tema": tema or f"t{id_}", "permitidos": list(permitidos)}}


class Sonda:
    """Runner falso que registra concurrencia máxima y solapamientos entre ids."""
    def __init__(self, resultado="pasa", demora=0.05, por_id=None):
        self.activos, self.maximo, self.solapes = set(), 0, []
        self.lock, self.resultado, self.demora, self.por_id = threading.Lock(), resultado, demora, por_id or {}
        self.lanzados = []

    def __call__(self, e):
        id_ = e["cfg"]["id"]
        with self.lock:
            self.solapes += [(id_, o) for o in self.activos]
            self.activos.add(id_)
            self.maximo = max(self.maximo, len(self.activos))
            self.lanzados.append(id_)
        time.sleep(self.demora)
        with self.lock:
            self.activos.discard(id_)
        return {"id": id_, "proyecto": "p", "resultado": self.por_id.get(id_, self.resultado)}


class TestSePisan(unittest.TestCase):
    def test_repos_distintos_no_se_pisan(self):
        self.assertFalse(cola.se_pisan(enc("1", repo="/a")["cfg"], enc("2", repo="/b")["cfg"]))

    def test_rutas_equivalentes_del_mismo_repo_se_serializan(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            relativa = str(repo / "." / "sub" / "..")
            absoluta = str(repo)
            self.assertTrue(cola.se_pisan(
                enc("1", repo=relativa, permitidos=["src/**"])["cfg"],
                enc("2", repo=absoluta, permitidos=["src/file.py"])["cfg"],
            ))

    def test_mismo_tema_se_pisan(self):
        self.assertTrue(cola.se_pisan(enc("1", tema="x", permitidos=["a/**"])["cfg"],
                                      enc("2", tema="x", permitidos=["b/**"])["cfg"]))

    def test_prefijos_anidados_se_pisan(self):
        self.assertTrue(cola.se_pisan(enc("1", permitidos=["tests/**"])["cfg"],
                                      enc("2", permitidos=["tests/test_a.py"])["cfg"]))

    def test_disjuntos_no_se_pisan(self):
        self.assertFalse(cola.se_pisan(enc("1", permitidos=["src/**"])["cfg"],
                                       enc("2", permitidos=["tests/**"])["cfg"]))

    def test_comodin_total_pisa_todo(self):
        self.assertTrue(cola.se_pisan(enc("1", permitidos=["**"])["cfg"], enc("2", permitidos=["src/x.py"])["cfg"]))


class TestAprobacionFinal(unittest.TestCase):
    def test_sin_revision_requerida_puede_cerrar_si_pasa(self):
        self.assertTrue(cola.todos_aprobados([{"resultado": "pasa"}]))


    def test_etapa_tests_preparados_debe_ser_consumida_por_un_dependiente_aprobado(self):
        etapa = {"id": "1", "proyecto": "p", "resultado": "tests_preparados"}
        self.assertFalse(cola.todos_aprobados([etapa]))
        cadena = [etapa, {"id": "2", "proyecto": "p", "depende_de": ["1"], "resultado": "pasa"}]
        self.assertTrue(cola.todos_aprobados(cadena))
        self.assertFalse(cola.todos_aprobados([{"resultado": "tests_no_fallan"}]))

    def test_revision_con_observaciones_bloquea_exito_de_cola(self):
        self.assertFalse(cola.todos_aprobados([
            {"resultado": "pasa", "aprobacion": "con_observaciones"}
        ]))

    def test_revision_fallida_bloquea_exito_de_cola(self):
        self.assertFalse(cola.todos_aprobados([
            {"resultado": "pasa", "aprobacion": "revision_error"}
        ]))

    def test_tests_fallidos_bloquean_aunque_revision_no_sea_requerida(self):
        self.assertFalse(cola.todos_aprobados([
            {"resultado": "falla_oraculo", "aprobacion": "no_requerida"}
        ]))


class TestRunnerSubproceso(unittest.TestCase):
    def test_runner_real_corta_despachador_bloqueado_en_oraculo(self):
        import os, shutil, subprocess, tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, home = root / "repo", root / "home"
            repo.mkdir()
            home.mkdir()
            (home / ".config" / "opencode" / "agents").mkdir(parents=True)
            (home / ".config" / "opencode" / "agents" / "tester.md").write_text("agent test\\n", encoding="utf-8")
            (home / "src").mkdir()
            run_git = lambda *args: subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                cwd=repo, check=True, capture_output=True, text=True
            )
            run_git("init", "-q", "-b", "main")
            (repo / "base.txt").write_text("base\n", encoding="utf-8")
            run_git("add", "base.txt")
            run_git("commit", "-qm", "base")
            proyecto = "queue-timeout-" + root.name.replace("-", "")[:8]
            encargo_id = "qto-" + root.name.replace("-", "")[:8]
            ruta = root / "encargo.md"
            ruta.write_text(
                '+++\nid = "' + encargo_id + '"\nproyecto = "' + proyecto + '"\nrepo = "' +
                str(repo) + '"\nagente = "tester"\ntema = "timeout"\nbase = "main"\n'
                'permitidos = ["tests/**"]\noraculo = ["sleep 20"]\n'
                'timeout_min = 1\ntimeout_cola_min = 2\n+++\n# timeout de prueba\n',
                encoding="utf-8",
            )
            run_base = Path(cola.despachar.__file__).resolve().parent / "runs" / f"{proyecto}-{encargo_id}"
            encargo = {"ruta": ruta, "cfg": {
                "id": encargo_id, "proyecto": proyecto, "timeout_min": 1, "timeout_cola_min": 0.05
            }}
            try:
                with patch.dict(os.environ, {"HOME": str(home)}):
                    estado = cola.runner_subproceso(encargo)
                self.assertEqual(estado["resultado"], "timeout_despachador", msg=str(estado))
                self.assertEqual(estado["timeout_s"], 3.0)
                self.assertFalse(any(run_base.glob("ronda-*/opencode.jsonl")),
                                 "OpenCode no debía iniciarse antes de finalizar el oráculo")
            finally:
                shutil.rmtree(run_base, ignore_errors=True)

    def test_timeout_real_termina_descendiente_que_ignora_sigterm(self):
        import os, signal, subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "sobrevivio.txt"
            hijo = (
                "import signal,time,pathlib; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(0.6); pathlib.Path(" + repr(str(marker)) + ").write_text('vivo')"
            )
            padre = (
                "import signal,subprocess,sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "p=subprocess.Popen([sys.executable, '-c', " + repr(hijo) + "]); p.wait()"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", padre], cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=True
            )
            stdout, stderr, agotado = cola.comunicar_con_timeout(proc, timeout_s=0.1, gracia_s=0.1)
            self.assertTrue(agotado, msg=f"stdout={stdout!r} stderr={stderr!r}")
            self.assertNotEqual(proc.poll(), None)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "el proceso descendiente sobrevivió al timeout del grupo")

    def test_timeout_termina_grupo_y_devuelve_estado_explicito(self):
        from unittest.mock import patch
        import subprocess, signal

        class ProcesoFalso:
            pid = 43210
            returncode = -signal.SIGTERM

            def __init__(self):
                self.llamadas = 0

            def communicate(self, timeout=None):
                self.llamadas += 1
                if self.llamadas == 1:
                    raise subprocess.TimeoutExpired("despachar", timeout, output="parcial", stderr="")
                return ("", "terminado")

        proceso = ProcesoFalso()
        encargo = {"ruta": Path("/tmp/encargo.md"),
                   "cfg": {"id": "t", "proyecto": "p", "timeout_cola_min": 1}}
        with patch("cola.subprocess.Popen", return_value=proceso), patch("cola.os.killpg") as matar:
            resultado = cola.runner_subproceso(encargo)
        self.assertEqual(resultado["resultado"], "timeout_despachador")
        self.assertEqual(resultado["timeout_s"], 60)
        matar.assert_called_once_with(proceso.pid, signal.SIGTERM)

    def test_timeout_persistente_escala_a_sigkill(self):
        from unittest.mock import patch
        import subprocess, signal

        class ProcesoFalso:
            pid = 43211
            returncode = -signal.SIGKILL

            def __init__(self):
                self.llamadas = 0

            def communicate(self, timeout=None):
                self.llamadas += 1
                if self.llamadas <= 2:
                    raise subprocess.TimeoutExpired("despachar", timeout, output="parcial", stderr="")
                return ("", "terminado")

        proceso = ProcesoFalso()
        encargo = {"ruta": Path("/tmp/encargo.md"),
                   "cfg": {"id": "t", "proyecto": "p", "timeout_cola_min": 1}}
        with patch("cola.subprocess.Popen", return_value=proceso), patch("cola.os.killpg") as matar:
            resultado = cola.runner_subproceso(encargo)
        self.assertEqual(resultado["resultado"], "timeout_despachador")
        self.assertEqual([call.args[1] for call in matar.call_args_list],
                         [signal.SIGTERM, signal.SIGKILL])


class TestDependencias(unittest.TestCase):
    def test_planifica_predecesor_antes_y_transmite_su_rama(self):
        primero = enc("1")
        segundo = enc("2")
        segundo["cfg"]["depende_de"] = ["1"]
        lanzados = []

        def runner(e):
            id_ = e["cfg"]["id"]
            lanzados.append((id_, e.get("base_dependencia")))
            if id_ == "1":
                return {"id": "1", "proyecto": "p", "resultado": "pasa", "rama": "opencode/primero"}
            return {"id": "2", "proyecto": "p", "resultado": "pasa", "rama": "opencode/segundo"}

        resultados = cola.planificar([segundo, primero], runner, max_paralelo=2)
        self.assertEqual([id_ for id_, _ in lanzados], ["1", "2"])
        self.assertIsNone(lanzados[0][1])
        self.assertEqual(lanzados[1][1], "opencode/primero")
        self.assertEqual([r["resultado"] for r in resultados], ["pasa", "pasa"])

    def test_no_lanza_dependiente_si_predecesor_falla(self):
        primero = enc("1")
        segundo = enc("2")
        segundo["cfg"]["depende_de"] = ["1"]
        lanzados = []

        def runner(e):
            lanzados.append(e["cfg"]["id"])
            return {"id": e["cfg"]["id"], "proyecto": "p",
                    "resultado": "falla_oraculo" if e["cfg"]["id"] == "1" else "pasa",
                    "rama": "opencode/primero"}

        resultados = cola.planificar([primero, segundo], runner, max_paralelo=2)
        self.assertEqual(lanzados, ["1"])
        self.assertEqual(next(r for r in resultados if r["id"] == "2")["resultado"], "dependencia_fallida")

    def test_encargo_temporal_cambia_base_sin_alterar_el_original(self):
        texto = '+++\nid = "2"\nproyecto = "p"\nrepo = "/r"\nagente = "implementador"\ntema = "impl"\nbase = "main"\npermitidos = ["src/**"]\noraculo = ["pytest -q"]\n+++\n# cuerpo\n'
        nuevo = cola._texto_con_base(texto, "opencode/primero")
        self.assertIn('base = "opencode/primero"', nuevo)
        self.assertIn('base = "main"', texto)
        sin_base = texto.replace('base = "main"\n', "")
        nuevo_sin_base = cola._texto_con_base(sin_base, "opencode/primero")
        self.assertIn('base = "opencode/primero"', nuevo_sin_base)

    def test_cargar_rechaza_dependencia_ausente_y_ciclos(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = '+++\nid = "{id}"\nproyecto = "p"\nrepo = "/repo"\nagente = "tester"\ntema = "tema{id}"\npermitidos = ["tests/**"]\noraculo = ["pytest -q"]\n{dep}+++\n# cuerpo\n'
            a = root / "a.md"
            a.write_text(base.format(id="1", dep='depende_de = ["9"]\n'), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no está en esta cola"):
                cola.cargar([a])
            a.write_text(base.format(id="1", dep='depende_de = ["2"]\n'), encoding="utf-8")
            b = root / "b.md"
            b.write_text(base.format(id="2", dep='depende_de = ["1"]\n'), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ciclo de dependencias"):
                cola.cargar([a, b])


class TestPlanificar(unittest.TestCase):
    def test_respeta_el_maximo_de_paralelismo(self):
        s = Sonda()
        cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(6)], s, max_paralelo=2)
        self.assertEqual(s.maximo, 2)
        self.assertEqual(len(s.lanzados), 6)

    def test_nunca_pasa_del_tope_duro(self):
        s = Sonda()
        cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(8)], s, max_paralelo=10)
        self.assertLessEqual(s.maximo, cola.MAX_PERMITIDO)

    def test_conflictivos_no_se_solapan(self):
        s = Sonda()
        cola.planificar([enc("1", permitidos=["tests/**"]), enc("2", permitidos=["tests/a.py"]),
                         enc("3", permitidos=["src/**"])], s, max_paralelo=3)
        self.assertNotIn(("2", "1"), s.solapes)
        self.assertNotIn(("1", "2"), s.solapes)
        self.assertEqual(sorted(s.lanzados), ["1", "2", "3"])

    def test_independientes_si_corren_juntos(self):
        s = Sonda(demora=0.15)
        cola.planificar([enc("1", permitidos=["a/**"]), enc("2", permitidos=["b/**"])], s, max_paralelo=2)
        self.assertTrue(s.solapes)

    def test_corta_tras_fallos_de_infraestructura_seguidos(self):
        s = Sonda(resultado="timeout")
        res = cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(6)], s, max_paralelo=1, corte_fallos=2)
        self.assertEqual(len(s.lanzados), 2)
        self.assertEqual(sum(1 for r in res if r["resultado"] == "no_lanzado"), 4)

    def test_un_exito_reinicia_la_racha(self):
        s = Sonda(por_id={"0": "timeout", "2": "timeout"})
        res = cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(4)], s, max_paralelo=1, corte_fallos=2)
        self.assertEqual(len(s.lanzados), 4)
        self.assertFalse(any(r["resultado"] == "no_lanzado" for r in res))

    def test_excepcion_del_runner_no_tumba_la_cola(self):
        def malo(e):
            if e["cfg"]["id"] == "1":
                raise RuntimeError("boom")
            return {"id": e["cfg"]["id"], "proyecto": "p", "resultado": "pasa"}
        res = cola.planificar([enc("1", permitidos=["a/**"]), enc("2", permitidos=["b/**"])], malo, max_paralelo=2)
        self.assertEqual({r["id"]: r["resultado"] for r in res}, {"1": "error_cola", "2": "pasa"})

    def test_excepciones_consecutivas_activan_corte_de_infraestructura(self):
        s = Sonda(por_id={str(i): "error_cola" for i in range(5)})
        def runner(e):
            s(e)
            raise RuntimeError("infraestructura")
        res = cola.planificar([enc(str(i), permitidos=[f"d{i}/**"]) for i in range(5)],
                              runner, max_paralelo=1, corte_fallos=2)
        self.assertEqual(len(s.lanzados), 2)
        self.assertEqual(sum(r["resultado"] == "no_lanzado" for r in res), 3)

    def test_cli_rechaza_paralelismo_fuera_de_rango(self):
        from unittest.mock import patch
        with patch("sys.argv", ["cola.py", "encargo.md", "--max", "0"]), \
             self.assertRaises(SystemExit) as salida:
            cola.main()
        self.assertEqual(salida.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
