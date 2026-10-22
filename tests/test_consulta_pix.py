import io
import json
import socket
import sys
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from consulta_pix import (ErroConsulta, SemRedirecionamentos, consultar_asaas,
                         formatar_resultado, normalizar_chave)


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


if __name__ == "__main__":
    unittest.main()
