import io
import json
import os
import queue
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from consulta_pix import (Aplicativo, ConsultaInconclusiva, ConsultaSemCadastro,
                         ErroConsulta, LimiteConsultas, SemRedirecionamentos, bloquear_cache, caminho_cache,
                         carregar_token, consultar_asaas, formatar_resultado,
                         normalizar_chave, registrar_consulta, resposta_sem_cadastro,
                         salvar_token, segundos_ate_liberar)


class ConsultaPixTests(unittest.TestCase):
    def test_normaliza_tipos_sem_mudar_chave(self):
        casos = [
            ("CPF", "123.456.789-00", "12345678900"),
            ("CNPJ", "12.345.678/0001-90", "12345678000190"),
            ("CNPJ", "99.999.a03/0001-06", "99999A03000106"),
            ("PHONE", "+55 (47) 99651-5839", "47996515839"),
            ("PHONE", "(47) 99651-5839", "47996515839"),
            ("EMAIL", "  TESTE@example.com ", "teste@example.com"),
            ("EVP", "123E4567-E89B-12D3-A456-426655440000", "123e4567-e89b-12d3-a456-426655440000"),
        ]
        for tipo, original, esperado in casos:
            with self.subTest(tipo=tipo, valor=original):
                self.assertEqual(normalizar_chave(tipo, original), esperado)

    def test_entrada_invalida_nao_faz_requisicao(self):
        casos = [
            ("CPF", ""), ("CPF", "123"), ("CPF", "abc12345678900"),
            ("CPF", "12345678900\n98765432100"),
            ("EMAIL", "primeiro@example.com;segundo@example.com"),
            ("EMAIL", "sem-arroba"), ("EVP", "abc"), ("PHONE", "555"),
        ]
        for tipo, chave in casos:
            abrir = Mock()
            with self.subTest(chave=chave), self.assertRaises(ErroConsulta):
                consultar_asaas("token-ficticio", tipo, chave, abrir)
            abrir.assert_not_called()

    def test_token_invalido_nao_faz_requisicao(self):
        for token in ("", "token\nquebrado", "$aact_hmlg_ficticio", "tökén"):
            abrir = Mock()
            with self.subTest(token=token), self.assertRaises(ErroConsulta):
                consultar_asaas(token, "CPF", "12345678900", abrir)
            abrir.assert_not_called()

    def test_envia_uma_unica_consulta_get_sem_body(self):
        dados = {"owner": {"name": "Titular de teste", "cpfCnpj": "***.456.789-**"},
                 "financialInstitution": {"name": "Banco de teste", "code": "000"},
                 "type": "EMAIL", "key": "teste+pix@example.com"}
        abrir = Mock(return_value=io.BytesIO(json.dumps(dados).encode()))
        self.assertEqual(consultar_asaas("token-ficticio", "EMAIL", "teste+pix@example.com", abrir), dados)
        abrir.assert_called_once()
        requisicao = abrir.call_args.args[0]
        self.assertEqual(requisicao.method, "GET")
        self.assertIsNone(requisicao.data)
        url = urllib.parse.urlsplit(requisicao.full_url)
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.netloc, "api.asaas.com")
        self.assertEqual(url.path, "/v3/pix/addressKeys/external")
        self.assertEqual(urllib.parse.parse_qs(url.query), {"type": ["EMAIL"], "key": ["teste+pix@example.com"]})
        self.assertEqual(requisicao.get_header("Access_token"), "token-ficticio")
        self.assertNotIn("token-ficticio", requisicao.full_url)
        self.assertEqual(abrir.call_args.kwargs["timeout"], 20)

    def test_retorno_legivel_com_schema_aninhado_e_fallback(self):
        texto = formatar_resultado({"owner": {"name": "Maria Teste", "cpfCnpj": "***.456.789-**"},
                                    "financialInstitution": {"name": "Banco de teste"}})
        self.assertIn("Titular\nMaria Teste", texto)
        self.assertIn("Instituição\nBanco de teste", texto)
        self.assertIn("CPF/CNPJ\n***.456.789-**", texto)
        self.assertIn("campo_novo", formatar_resultado({"campo_novo": "visível"}))

    def test_erros_http_nao_confirmam_inexistencia_nem_expoem_token(self):
        for status in (400, 401, 403, 404, 429, 500, 503):
            resposta = io.BytesIO(json.dumps({"errors": [{"description": "Detalhe token-ficticio"}]}).encode())
            erro = urllib.error.HTTPError("https://api.asaas.com", status, "Erro", {}, resposta)
            abrir = Mock(side_effect=erro)
            with self.subTest(status=status), self.assertRaises(ErroConsulta) as contexto:
                consultar_asaas("token-ficticio", "CPF", "12345678900", abrir)
            mensagem = str(contexto.exception)
            self.assertIn(f"HTTP {status}", mensagem)
            self.assertIn("Detalhe", mensagem)
            self.assertNotIn("token-ficticio", mensagem)
            self.assertNotIn("chave inexistente", mensagem.lower())
            abrir.assert_called_once()

    def test_respostas_invalidas_nao_sao_sucesso(self):
        for bruto in (b"<html>erro</html>", b"null", b"{}", b"[]", b"x" * 262145,
                      b'{"errors":[{"description":"Falha do provedor"}]}'):
            with self.subTest(bruto=bruto[:30]), self.assertRaises(ErroConsulta):
                consultar_asaas("token-ficticio", "CPF", "12345678900", Mock(return_value=io.BytesIO(bruto)))

    def test_falhas_de_rede_sem_repeticao_automatica(self):
        for erro in (socket.timeout(), urllib.error.URLError("Offline")):
            abrir = Mock(side_effect=erro)
            with self.subTest(erro=erro), self.assertRaises(ErroConsulta):
                consultar_asaas("token-ficticio", "CPF", "12345678900", abrir)
            abrir.assert_called_once()

    def test_nao_redireciona_token(self):
        handler = SemRedirecionamentos()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://outro.example.com"))

    def test_sem_cadastro_exige_descricao_explicita(self):
        for descricao in ("Chave Pix não encontrada.", "Chave Pix informada não está cadastrada.",
                          "Não foi encontrada uma chave Pix para o CPF informado.",
                          "CPF não possui chave Pix cadastrada.", "Pix key not found.",
                          "CPF não cadastrado como chave Pix.",
                          "Chave Pix não registrada."):
            for status in (400, 404):
                with self.subTest(descricao=descricao, status=status):
                    dados = {"errors": [{"description": descricao}]}
                    self.assertTrue(resposta_sem_cadastro(status, dados))
                    erro = urllib.error.HTTPError("https://api.asaas.com", status, "Erro", {},
                                                 io.BytesIO(json.dumps(dados).encode()))
                    with self.assertRaises(ConsultaSemCadastro) as contexto:
                        consultar_asaas("token-ficticio", "CPF", "12345678900", Mock(side_effect=erro))
                    self.assertEqual(str(contexto.exception), "Sucesso, CPF sem Pix cadastrado.")

    def test_limites_acesso_e_codigos_genericos_nao_sao_sem_cadastro(self):
        casos = [
            {"code": "invalid_action", "description": "Tentativas excedidas."},
            {"code": "not_found", "description": "Recurso não encontrado."},
            {"code": "pix_key_not_found"},
            {"description": "Chave de API não encontrada."},
            {"description": "Chave Pix não encontrada devido ao limite de consultas."},
            {"description": "Chave Pix não encontrada ou acesso negado."},
            {"description": "Chave Pix não encontrada devido à cota esgotada."},
            {"description": "Chave Pix não encontrada: operação não permitida."},
            {"description": "Chave Pix não encontrada: autorização negada."},
            {"description": "Pix key not found: forbidden or access denied."},
            {"description": "Chave Pix não encontrada por restrição de segurança."},
            {"description": "Não foi possível encontrar a chave Pix por indisponibilidade."},
            {"description": "Chave Pix bloqueada por suspeita de fraude."},
        ]
        for erro in casos:
            with self.subTest(erro=erro):
                self.assertFalse(resposta_sem_cadastro(400, {"errors": [erro]}))
        misturado = {"errors": [{"description": "Chave Pix não encontrada."},
                                 {"description": "Tentativas excedidas."}]}
        self.assertFalse(resposta_sem_cadastro(400, misturado))
        for status in (401, 403, 429, 500):
            self.assertFalse(resposta_sem_cadastro(status, {"errors": [{"description": "Chave Pix não encontrada."}]}))

    def test_http404_vazio_e_sem_cadastro_neste_fluxo(self):
        erro = urllib.error.HTTPError("https://api.asaas.com", 404, "Not Found", {}, io.BytesIO(b""))
        with self.assertRaises(ConsultaSemCadastro) as contexto:
            consultar_asaas("token-ficticio", "CPF", "12345678900", Mock(side_effect=erro))
        self.assertEqual("Sucesso, CPF sem Pix cadastrado.", str(contexto.exception))

    def test_worker_separa_resultado_confirmado_erro_e_inconclusivo(self):
        app = Aplicativo.__new__(Aplicativo)
        app.fila = queue.Queue()
        for excecao, esperado in ((ConsultaSemCadastro("CPF"), "sem_cadastro"),
                                 (ConsultaInconclusiva("Resposta inconclusiva"), "inconclusivo"),
                                 (ErroConsulta("Tentativas excedidas"), "erro")):
            with self.subTest(esperado=esperado), patch("consulta_pix.consultar_asaas", side_effect=excecao):
                app.executar("token-ficticio", "CPF", "12345678900")
                estado, texto = app.fila.get_nowait()
                self.assertEqual(estado, esperado)
                self.assertEqual(texto, str(excecao))


class CacheTokenTests(unittest.TestCase):
    def test_salvar_e_carregar_preserva_token_sem_interpolacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            token = "$aact_prod_ficticio%abc=123"
            self.assertEqual(carregar_token(arquivo), "")
            salvar_token(token, arquivo)
            self.assertEqual(carregar_token(arquivo), token)
            self.assertIn("[consulta_pix]", arquivo.read_text(encoding="utf-8"))
            if os.name != "nt":
                self.assertEqual(arquivo.stat().st_mode & 0o777, 0o600)
            salvar_token("novo-token-ficticio", arquivo)
            self.assertEqual(carregar_token(arquivo), "novo-token-ficticio")

    def test_cache_fica_na_pasta_do_programa_independente_do_cwd(self):
        cwd_original = Path.cwd()
        with tempfile.TemporaryDirectory() as pasta:
            base = Path(pasta)
            programa = base / "programa"
            outra = base / "atalho"
            programa.mkdir()
            outra.mkdir()
            try:
                os.chdir(outra)
                with patch("consulta_pix.__file__", str(programa / "consulta_pix.py")):
                    salvar_token("token-ficticio")
                    self.assertEqual(caminho_cache(), programa / "cache.ini")
                    self.assertEqual(carregar_token(), "token-ficticio")
                    self.assertFalse((outra / "cache.ini").exists())
            finally:
                os.chdir(cwd_original)

    def test_cache_usa_diretorio_executavel_quando_frozen(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "/tmp/consulta-pix/ConsultaPix.exe"):
            self.assertEqual(caminho_cache(), Path("/tmp/consulta-pix/cache.ini"))

    def test_falha_ao_salvar_preserva_anterior_e_nao_expoe_token(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            salvar_token("token-anterior", arquivo)
            with patch("consulta_pix.os.replace", side_effect=PermissionError("token-novo")):
                with self.assertRaises(ErroConsulta) as contexto:
                    salvar_token("token-novo", arquivo)
            self.assertNotIn("token-novo", str(contexto.exception))
            self.assertEqual(carregar_token(arquivo), "token-anterior")
            self.assertEqual(list(Path(pasta).glob("*.tmp")), [])

    def test_cache_invalido_nao_expoe_conteudo(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            arquivo.write_text("token-secreto-sem-secao", encoding="utf-8")
            with self.assertRaises(ErroConsulta) as contexto:
                carregar_token(arquivo)
            self.assertNotIn("token-secreto", str(contexto.exception))

    def test_salvar_so_acontece_no_botao_quando_ocioso(self):
        app = Aplicativo.__new__(Aplicativo)
        app.ocupado = False
        app.token = Mock()
        app.token.get.return_value = "token-ficticio"
        app.status = Mock()
        with patch("consulta_pix.salvar_token") as salvar:
            app.salvar()
            salvar.assert_called_once_with("token-ficticio")
            app.ocupado = True
            app.salvar()
            salvar.assert_called_once()


class LimitePersistenteTests(unittest.TestCase):
    def test_uma_consulta_por_minuto_e_contagem_regressiva(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1000), 0)
            registrar_consulta(arquivo, agora=1000)
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1001), 59)
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1010), 50)
            with self.assertRaises(LimiteConsultas) as contexto:
                registrar_consulta(arquivo, agora=1011)
            self.assertEqual(contexto.exception.segundos, 49)
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1059.9), 1)
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1060), 0)
            registrar_consulta(arquivo, agora=1060)
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1060), 60)
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1120), 0)

    def test_salvar_token_preserva_horarios_e_registrar_nao_salva_token(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            registrar_consulta(arquivo, agora=1000)
            self.assertEqual(carregar_token(arquivo), "")
            self.assertNotIn("[consulta_pix]", arquivo.read_text(encoding="utf-8"))
            salvar_token("token-salvo", arquivo)
            registrar_consulta(arquivo, agora=1060)
            salvar_token("token-substituto", arquivo)
            self.assertEqual(carregar_token(arquivo), "token-substituto")
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1060), 60)

    def test_horarios_sobrevivem_nova_leitura_e_reabertura(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            registrar_consulta(arquivo, agora=2000)
            original = arquivo.read_bytes()
            self.assertEqual(segundos_ate_liberar(Path(str(arquivo)), agora=2030), 30)
            with self.assertRaises(LimiteConsultas):
                registrar_consulta(arquivo, agora=2030)
            self.assertEqual(arquivo.read_bytes(), original)

    def test_historico_invalido_falha_sem_apagar_o_cache(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            for horarios in ("nao-json", "[true]", "[NaN]", "[-1]", '{}'):
                original = f"[limite]\ntimestamps = {horarios}\n"
                arquivo.write_text(original, encoding="utf-8")
                with self.subTest(horarios=horarios), self.assertRaises(ErroConsulta):
                    registrar_consulta(arquivo, agora=1000)
                self.assertEqual(arquivo.read_text(encoding="utf-8"), original)

    def test_segunda_janela_nao_sobrescreve_cache_bloqueado(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            registrar_consulta(arquivo, agora=1000)
            with bloquear_cache(arquivo), self.assertRaises(ErroConsulta):
                registrar_consulta(arquivo, agora=1001)
            self.assertEqual(segundos_ate_liberar(arquivo, agora=1001), 59)

    @staticmethod
    def app_para_consulta():
        app = Aplicativo.__new__(Aplicativo)
        app.ocupado = False
        app.token = Mock()
        app.token.get.return_value = "token-digitado-nao-salvo"
        app.tipo = Mock()
        app.tipo.get.return_value = "CPF"
        app.chave = Mock()
        app.chave.get.return_value = "12345678900"
        for nome in ("status", "botao", "botao_salvar", "progresso", "escrever", "atualizar_limite"):
            setattr(app, nome, Mock())
        return app

    def test_interface_persiste_antes_thread_sem_salvar_token_digitado(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "cache.ini"
            salvar_token("token-ja-salvo", arquivo)
            app = self.app_para_consulta()

            def criar_thread(*args, **kwargs):
                self.assertEqual(carregar_token(arquivo), "token-ja-salvo")
                texto = arquivo.read_text(encoding="utf-8")
                self.assertIn("1000", texto)
                self.assertNotIn("token-digitado-nao-salvo", texto)
                return Mock()

            with patch("consulta_pix.caminho_cache", return_value=arquivo), patch("consulta_pix.time.time", return_value=1000), patch("consulta_pix.threading.Thread", side_effect=criar_thread) as thread:
                app.consultar()
                thread.assert_called_once()

    def test_interface_nao_envia_quando_historico_nao_pode_ser_gravado(self):
        app = self.app_para_consulta()
        with patch("consulta_pix.registrar_consulta", side_effect=ErroConsulta("Sem permissão de gravação")), patch("consulta_pix.threading.Thread") as thread:
            app.consultar()
            thread.assert_not_called()
            self.assertFalse(app.ocupado)

    def test_interface_nao_conta_token_ou_chave_invalidos(self):
        for token, chave in (("", "12345678900"), ("$aact_hmlg_ficticio", "12345678900"), ("token-ficticio", "123")):
            app = self.app_para_consulta()
            app.token.get.return_value = token
            app.chave.get.return_value = chave
            with self.subTest(token=token, chave=chave), patch("consulta_pix.registrar_consulta") as registrar, patch("consulta_pix.threading.Thread") as thread:
                app.consultar()
                registrar.assert_not_called()
                thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
