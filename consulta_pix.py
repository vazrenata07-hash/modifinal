#!/usr/bin/env python3
"""Consulta manual de uma chave Pix. Python 3.9+, sem pip."""

import configparser
import json
import math
import os
import queue
import re
import socket
import ssl
import sys
import tempfile
import threading
import time
import tkinter as tk
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from contextlib import contextmanager
from tkinter import ttk


ENDPOINT = "https://api.asaas.com/v3/pix/addressKeys/external"
TIPOS = {"CPF": "CPF", "CNPJ": "CNPJ", "E-mail": "EMAIL",
         "Telefone": "PHONE", "Aleatória": "EVP"}
MAX_RESPOSTA = 262144
COR_SUCESSO_SUAVE = "#4d8268"
FUNDO_SUCESSO_SUAVE = "#edf7ef"
MAX_CONSULTAS = 2
INTERVALO_CONSULTAS = 120


class ErroConsulta(Exception):
    """Mensagem que pode ser mostrada na interface."""


class ConsultaSemCadastro(ErroConsulta):
    """Resultado sem cadastro, incluindo o HTTP 404 sem detalhes deste fluxo."""

    def __init__(self, tipo):
        self.tipo = tipo
        mensagens = {
            "CPF": "Sucesso, CPF sem Pix cadastrado.",
            "CNPJ": "Sucesso, CNPJ sem Pix cadastrado.",
            "EMAIL": "Sucesso, e-mail sem Pix cadastrado.",
            "PHONE": "Sucesso, telefone sem Pix cadastrado.",
            "EVP": "Sucesso, chave sem Pix cadastrado.",
        }
        super().__init__(mensagens.get(tipo, "Sucesso, chave sem Pix cadastrado."))


class ConsultaInconclusiva(ErroConsulta):
    """A resposta não distingue chave sem cadastro de recurso indisponível."""


class LimiteConsultas(ErroConsulta):
    def __init__(self, segundos):
        self.segundos = segundos
        minutos, resto = divmod(segundos, 60)
        super().__init__(f"Aguarde {minutos:02d}:{resto:02d} para consultar novamente.")


def caminho_cache():
    """A pasta do programa independe da pasta atual do terminal ou atalho."""
    programa = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
    return programa.resolve().parent / "cache.ini"


def validar_token(token):
    token = token.strip()
    if not token:
        raise ErroConsulta("Cole seu token de produção.")
    if len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ErroConsulta("O token contém espaços ou caracteres inválidos. Copie-o novamente.")
    if token.startswith("$aact_hmlg_"):
        raise ErroConsulta("Esse token é de testes (sandbox). Use um token de produção para consultar chaves reais.")
    return token


def carregar_token(caminho=None):
    destino = Path(caminho) if caminho is not None else caminho_cache()
    try:
        configuracao = ler_configuracao(destino)
        token = configuracao.get("consulta_pix", "token", fallback="")
        return validar_token(token) if token else ""
    except ErroConsulta:
        raise ErroConsulta("Não foi possível carregar o token do cache.ini. Confira o arquivo e as permissões da pasta.") from None


def ler_configuracao(destino):
    configuracao = configparser.ConfigParser(interpolation=None)
    try:
        with Path(destino).open("r", encoding="utf-8") as arquivo:
            configuracao.read_file(arquivo)
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError, configparser.Error):
        raise ErroConsulta("Não foi possível ler o cache.ini. Confira o arquivo e as permissões da pasta.") from None
    return configuracao


@contextmanager
def bloquear_cache(destino):
    """Evita perda de horários quando duas janelas compartilham o mesmo INI."""
    arquivo = None
    bloqueado = False
    try:
        descritor = os.open(str(Path(destino).with_name(".cache.ini.lock")), os.O_RDWR | os.O_CREAT, 0o600)
        arquivo = os.fdopen(descritor, "r+b")
        if os.fstat(arquivo.fileno()).st_size == 0:
            arquivo.write(b"\0")
            arquivo.flush()
        arquivo.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        bloqueado = True
        yield
    except OSError:
        raise ErroConsulta("Não foi possível atualizar o cache.ini. Confira a permissão da pasta ou aguarde a outra janela terminar.") from None
    finally:
        if arquivo is not None:
            if bloqueado:
                arquivo.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(arquivo.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)
            arquivo.close()


def gravar_configuracao(configuracao, destino):
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destino.parent,
                                         prefix=".consulta-pix-", suffix=".tmp", delete=False) as arquivo:
            temporario = Path(arquivo.name)
            if os.name != "nt":
                os.chmod(temporario, 0o600)
            configuracao.write(arquivo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    except OSError:
        raise ErroConsulta("Não foi possível salvar o cache.ini. Extraia o programa para uma pasta em que você tenha permissão de gravação.") from None
    finally:
        if temporario is not None:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass


def salvar_token(token, caminho=None):
    token = validar_token(token)
    destino = Path(caminho) if caminho is not None else caminho_cache()
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        configuracao["consulta_pix"] = {"token": token}
        gravar_configuracao(configuracao, destino)


def historico_ativo(configuracao, agora):
    try:
        horarios = json.loads(configuracao.get("limite", "timestamps", fallback="[]"))
        if not isinstance(horarios, list) or len(horarios) > 100:
            raise ValueError
        if any(isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(h) or h < 0 for h in horarios):
            raise ValueError
        return sorted(float(h) for h in horarios if agora - h < INTERVALO_CONSULTAS)
    except (ValueError, TypeError, configparser.Error):
        raise ErroConsulta("O histórico de consultas do cache.ini é inválido. Confira o arquivo antes de continuar.") from None


def espera_historico(horarios, agora):
    if len(horarios) < MAX_CONSULTAS:
        return 0
    return max(0, math.ceil(horarios[-MAX_CONSULTAS] + INTERVALO_CONSULTAS - agora))


def segundos_ate_liberar(caminho=None, agora=None):
    destino = Path(caminho) if caminho is not None else caminho_cache()
    agora = time.time() if agora is None else agora
    return espera_historico(historico_ativo(ler_configuracao(destino), agora), agora)


def registrar_consulta(caminho=None, agora=None):
    """Persiste a tentativa antes de enviar; não salva o token digitado."""
    destino = Path(caminho) if caminho is not None else caminho_cache()
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        agora = time.time() if agora is None else agora
        horarios = historico_ativo(configuracao, agora)
        espera = espera_historico(horarios, agora)
        if espera:
            raise LimiteConsultas(espera)
        horarios.append(agora)
        if not configuracao.has_section("limite"):
            configuracao.add_section("limite")
        configuracao.set("limite", "timestamps", json.dumps(horarios))
        gravar_configuracao(configuracao, destino)


def normalizar_texto_erro(valor):
    texto = unicodedata.normalize("NFD", str(valor).lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def resposta_sem_cadastro(status, dados):
    """Neste fluxo, 404 sem detalhes é sem cadastro; limites têm prioridade."""
    if status not in (400, 404) or not isinstance(dados, dict):
        return False
    erros = dados.get("errors")
    if not erros and any(dados.get(campo) for campo in ("code", "description", "message")):
        erros = [{"code": dados.get("code", ""),
                  "description": dados.get("description") or dados.get("message", "")}]
    if not isinstance(erros, list) or not erros:
        return status == 404 and not erros and not dados.get("error")
    confirmado = False
    for erro in erros:
        if not isinstance(erro, dict):
            return False
        codigo = normalizar_texto_erro(erro.get("code", ""))
        descricao = normalizar_texto_erro(erro.get("description", ""))
        combinado = codigo + " " + descricao
        if any(termo in combinado for termo in ("limit", "exced", "excess", "cota", "quota", "esgot", "tentativ", "rate_", "too_many", "bloque", "restric", "token", "permission", "permiss", "unauthor", "acesso", "autoriz", "forbidden", "denied", "nao permit", "segur", "fraud", "indispon", "unavail", "nao foi possivel")):
            return False
        descricao_explicita = (
            re.search(r"(?:chave\s+pix|pix\s+key).{0,60}(?:nao\s+(?:foi\s+)?encontrad[ao]|nao\s+(?:esta\s+)?(?:cadastrad[ao]|registrad[ao])|not\s+found|nao\s+existe)", descricao)
            or re.search(r"nao\s+(?:foi\s+)?encontrad[ao].{0,40}chave\s+pix", descricao)
            or re.search(r"(?:cpf|cnpj|telefone|e-mail|email).{0,40}nao\s+possui.{0,20}(?:chave\s+)?pix", descricao)
            or re.search(r"(?:cpf|cnpj|telefone|e-mail|email).{0,30}nao\s+(?:esta\s+)?cadastrad[ao]\s+como\s+chave\s+pix", descricao)
        )
        if descricao_explicita:
            confirmado = True
        else:
            return False
    return confirmado


def normalizar_chave(tipo, valor):
    valor = valor.strip()
    if not valor or len(valor) > 200:
        raise ErroConsulta("Digite uma única chave Pix.")
    if any(ord(c) < 32 for c in valor):
        raise ErroConsulta("Digite apenas uma chave, sem quebras de linha.")
    if tipo == "CNPJ":
        if not re.fullmatch(r"[A-Za-z0-9\s./\-]+", valor):
            raise ErroConsulta("Confira o CNPJ informado.")
        cnpj = re.sub(r"[\s./\-]", "", valor).upper()
        if not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", cnpj):
            raise ErroConsulta("CNPJ: informe 14 caracteres, com os dois últimos numéricos.")
        return cnpj
    if tipo in ("CPF", "PHONE"):
        if not re.fullmatch(r"[0-9\s.()/+\-]+", valor):
            raise ErroConsulta("Use somente números e a pontuação da chave.")
        numeros = re.sub(r"[^0-9]", "", valor)
        if tipo == "PHONE" and len(numeros) == 13 and numeros.startswith("55"):
            numeros = numeros[2:]
        if len(numeros) != 11:
            detalhe = "Telefone: informe DDD + número, com 11 dígitos." if tipo == "PHONE" else "CPF: informe 11 dígitos."
            raise ErroConsulta(detalhe)
        return numeros
    if tipo == "EMAIL":
        if len(valor) > 77 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", valor):
            raise ErroConsulta("Confira o e-mail informado.")
        return valor.lower()
    if tipo == "EVP":
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", valor):
            raise ErroConsulta("Confira a chave aleatória: copie os 36 caracteres, incluindo os hífens.")
        return valor.lower()
    raise ErroConsulta("Selecione o tipo da chave Pix.")


def limpar_texto(valor):
    return "".join(c for c in str(valor) if c in "\n\t" or ord(c) >= 32)


def mensagem_http(status, dados, token):
    mensagens = {
        400: "Não foi possível consultar essa chave. Confira o motivo abaixo.",
        401: "Token não autorizado. Confira se ele é de produção, está válido e foi copiado inteiro.",
        403: "Acesso negado. Confira a aprovação da conta e as permissões da API.",
        404: "Não foi possível confirmar se a chave está cadastrada. Veja a resposta do serviço abaixo.",
        429: "Limite de consultas ou cota atingido. Aguarde antes de tentar novamente.",
    }
    mensagem = mensagens.get(status, "O serviço está indisponível no momento." if status >= 500 else "Não foi possível concluir a consulta.")
    detalhes = []
    if isinstance(dados, dict):
        erros = dados.get("errors", [])
        if isinstance(erros, list):
            for erro in erros[:3]:
                if isinstance(erro, dict) and isinstance(erro.get("description"), str):
                    detalhes.append(limpar_texto(erro["description"])[:500])
    texto = f"{mensagem}\n\nHTTP {status}"
    if detalhes:
        texto += "\n" + "\n".join(detalhes)
    return texto.replace(token, "[token oculto]") if token else texto


class SemRedirecionamentos(urllib.request.HTTPRedirectHandler):
    """Não encaminhe o token para outro endereço por redirecionamento."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def consultar_asaas(token, tipo, chave, abrir=None):
    token = validar_token(token)
    chave = normalizar_chave(tipo, chave)
    url = ENDPOINT + "?" + urllib.parse.urlencode({"type": tipo, "key": chave})
    requisicao = urllib.request.Request(url, method="GET", headers={
        "access_token": token,
        "User-Agent": "ConsultaPixLocal/1.0",
        "Accept": "application/json",
    })
    if abrir is None:
        abrir = urllib.request.build_opener(SemRedirecionamentos()).open
    try:
        with abrir(requisicao, timeout=20) as resposta:
            bruto = resposta.read(MAX_RESPOSTA + 1)
        if len(bruto) > MAX_RESPOSTA:
            raise ErroConsulta("O serviço retornou uma resposta maior que o esperado.")
        dados = json.loads(bruto.decode("utf-8-sig"))
        if not isinstance(dados, dict) or not dados:
            raise ErroConsulta("O serviço retornou uma resposta inesperada. Não foi possível confirmar a chave.")
        if dados.get("errors"):
            if resposta_sem_cadastro(400, dados):
                raise ConsultaSemCadastro(tipo)
            raise ErroConsulta(mensagem_http(400, dados, token))
        return dados
    except urllib.error.HTTPError as erro:
        try:
            dados = json.loads(erro.read(MAX_RESPOSTA).decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            dados = {}
        finally:
            erro.close()
        if resposta_sem_cadastro(erro.code, dados):
            raise ConsultaSemCadastro(tipo) from None
        if erro.code == 404:
            raise ConsultaInconclusiva(mensagem_http(erro.code, dados, token)) from None
        raise ErroConsulta(mensagem_http(erro.code, dados, token)) from None
    except (TimeoutError, socket.timeout):
        raise ErroConsulta("O serviço demorou para responder. Confira a conexão e tente novamente.") from None
    except urllib.error.URLError as erro:
        if isinstance(erro.reason, ssl.SSLError):
            raise ErroConsulta("Não foi possível validar a conexão segura. Confira a data do computador e os certificados do Python.") from None
        raise ErroConsulta("Não foi possível conectar ao serviço. Confira sua internet e tente novamente.") from None
    except (ValueError, UnicodeError):
        raise ErroConsulta("O serviço retornou uma resposta que não foi possível ler. Tente novamente mais tarde.") from None
    except OSError:
        raise ErroConsulta("Não foi possível estabelecer a conexão segura com o serviço.") from None


def formatar_resultado(dados):
    titular = dados.get("owner") if isinstance(dados.get("owner"), dict) else {}
    banco = dados.get("financialInstitution") if isinstance(dados.get("financialInstitution"), dict) else {}
    campos = [
        ("Titular", titular.get("name") or dados.get("ownerName") or dados.get("name")),
        ("CPF/CNPJ", titular.get("cpfCnpj") or dados.get("cpfCnpj")),
        ("Instituição", banco.get("name") or dados.get("ispbName")),
        ("Código do banco", banco.get("code")),
        ("Chave", dados.get("key")),
        ("Tipo", dados.get("type")),
    ]
    resumo = "\n\n".join(f"{rotulo}\n{limpar_texto(valor)}" for rotulo, valor in campos if valor is not None and valor != "")
    completo = json.dumps(dados, ensure_ascii=False, indent=2)
    return (resumo + "\n\n── Resposta completa ──\n\n" + completo) if resumo else completo


class Aplicativo:
    def __init__(self, janela):
        self.janela = janela
        self.fila = queue.Queue()
        self.ocupado = False
        self.fechado = False
        janela.title("Consultar Pix")
        janela.geometry("650x690")
        janela.minsize(520, 600)
        janela.configure(bg="#f3f6f5")
        janela.protocol("WM_DELETE_WINDOW", self.fechar)

        estilo = ttk.Style(janela)
        if "clam" in estilo.theme_names():
            estilo.theme_use("clam")
        estilo.configure("TFrame", background="#f3f6f5")
        estilo.configure("TLabel", background="#f3f6f5", foreground="#183c35", font=("Segoe UI", 10))
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 23, "bold"))
        estilo.configure("Ajuda.TLabel", foreground="#526d66", font=("Segoe UI", 9))
        estilo.configure("TEntry", padding=9, font=("Segoe UI", 11))
        estilo.configure("TCombobox", padding=8, font=("Segoe UI", 10))
        estilo.configure("TCheckbutton", background="#f3f6f5", font=("Segoe UI", 9))
        estilo.configure("Consultar.TButton", padding=12, font=("Segoe UI", 11, "bold"), background="#116b55", foreground="white")
        estilo.map("Consultar.TButton", background=[("disabled", "#99aaa5"), ("active", "#0c5845")])

        conteudo = ttk.Frame(janela, padding=26)
        conteudo.pack(fill="both", expand=True)
        conteudo.columnconfigure(0, weight=1)
        conteudo.rowconfigure(10, weight=1)
        ttk.Label(conteudo, text="Consultar Pix", style="Titulo.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(conteudo, text="Uma chave por vez", style="Ajuda.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 22))

        linha_token = ttk.Frame(conteudo)
        linha_token.grid(row=2, column=0, sticky="ew")
        ttk.Label(linha_token, text="Token").pack(side="left")
        self.mostrar_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(linha_token, text="Mostrar", variable=self.mostrar_token, command=self.alternar_token).pack(side="right")
        campo_token = ttk.Frame(conteudo)
        campo_token.grid(row=3, column=0, sticky="ew", pady=(5, 4))
        campo_token.columnconfigure(0, weight=1)
        self.token = ttk.Entry(campo_token, show="*")
        self.token.grid(row=0, column=0, sticky="ew")
        self.botao_salvar = ttk.Button(campo_token, text="Salvar", command=self.salvar)
        self.botao_salvar.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(conteudo, text="Salvar guarda o token no cache.ini desta pasta.", style="Ajuda.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 17))

        linha = ttk.Frame(conteudo)
        linha.grid(row=5, column=0, sticky="ew")
        linha.columnconfigure(1, weight=1)
        ttk.Label(linha, text="Tipo").grid(row=0, column=0, sticky="w")
        ttk.Label(linha, text="Chave Pix").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.tipo = ttk.Combobox(linha, values=list(TIPOS), state="readonly", width=12)
        self.tipo.set("CPF")
        self.tipo.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.chave = ttk.Entry(linha)
        self.chave.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(5, 0))
        self.botao = ttk.Button(conteudo, text="Consultar", style="Consultar.TButton", command=self.consultar)
        self.botao.grid(row=6, column=0, sticky="ew", pady=(18, 10))
        self.status = ttk.Label(conteudo, text="Pronto para consultar.", style="Ajuda.TLabel", wraplength=550)
        self.status.grid(row=7, column=0, sticky="w", pady=(0, 16))
        self.progresso = ttk.Progressbar(conteudo, mode="indeterminate")
        self.progresso.grid(row=8, column=0, sticky="ew", pady=(0, 10))
        self.progresso.grid_remove()
        ttk.Label(conteudo, text="Resultado").grid(row=9, column=0, sticky="w", pady=(0, 7))
        caixa = ttk.Frame(conteudo)
        caixa.grid(row=10, column=0, sticky="nsew")
        self.resultado = tk.Text(caixa, wrap="word", font=("Segoe UI", 10), padx=14, pady=14,
                                 bg="white", fg="#183c35", relief="solid", borderwidth=1,
                                 highlightthickness=0, height=10, state="disabled")
        barra = ttk.Scrollbar(caixa, orient="vertical", command=self.resultado.yview)
        self.resultado.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.resultado.pack(side="left", fill="both", expand=True)
        ttk.Label(conteudo, text="Somente consulta. Nenhuma transferência é realizada.", style="Ajuda.TLabel").grid(row=11, column=0, sticky="w", pady=(15, 0))
        self.escrever("O retorno da consulta aparecerá aqui.")
        janela.bind("<Return>", lambda evento: self.consultar())
        try:
            token_salvo = carregar_token()
        except ErroConsulta as erro:
            token_salvo = ""
            self.status.configure(text=str(erro), foreground="#a13d29")
        if token_salvo:
            self.token.insert(0, token_salvo)
            self.status.configure(text="Token carregado do cache.ini.", foreground=COR_SUCESSO_SUAVE)
            self.chave.focus_set()
        else:
            self.token.focus_set()
        self.janela.after(100, self.receber_resultado)
        self.atualizar_limite()

    def alternar_token(self):
        self.token.configure(show="" if self.mostrar_token.get() else "*")

    def salvar(self):
        if self.ocupado:
            return
        try:
            salvar_token(self.token.get())
        except ErroConsulta as erro:
            self.status.configure(text=str(erro), foreground="#a13d29")
        else:
            self.status.configure(text="Token salvo no cache.ini.", foreground=COR_SUCESSO_SUAVE)

    def atualizar_limite(self, reagendar=True):
        if self.fechado:
            return
        if not self.ocupado:
            try:
                segundos = segundos_ate_liberar()
            except ErroConsulta as erro:
                self.botao.configure(state="disabled", text="Consultar")
                self.status.configure(text=str(erro), foreground="#a13d29")
            else:
                if segundos:
                    minutos, resto = divmod(segundos, 60)
                    self.botao.configure(state="disabled", text=f"Consultar ({minutos:02d}:{resto:02d})")
                else:
                    self.botao.configure(state="normal", text="Consultar")
        if reagendar:
            self.janela.after(1000, self.atualizar_limite)

    def escrever(self, texto, sem_cadastro=False, inconclusivo=False):
        self.resultado.configure(state="normal", bg=FUNDO_SUCESSO_SUAVE if sem_cadastro else "#fff8e6" if inconclusivo else "white",
                                 fg=COR_SUCESSO_SUAVE if sem_cadastro else "#775d2b" if inconclusivo else "#183c35")
        self.resultado.delete("1.0", "end")
        self.resultado.insert("1.0", texto)
        self.resultado.configure(state="disabled")

    def consultar(self):
        if self.ocupado:
            return
        tipo = TIPOS.get(self.tipo.get())
        try:
            token = validar_token(self.token.get())
            chave = normalizar_chave(tipo, self.chave.get())
            registrar_consulta()
        except LimiteConsultas as erro:
            self.status.configure(text=str(erro), foreground="#775d2b")
            self.atualizar_limite(reagendar=False)
            return
        except ErroConsulta as erro:
            self.status.configure(text=str(erro), foreground="#a13d29")
            self.escrever("Consulta não enviada. Confira os campos acima.")
            self.atualizar_limite(reagendar=False)
            return
        self.ocupado = True
        self.botao.configure(state="disabled", text="Consultando…")
        self.tipo.configure(state="disabled")
        self.chave.configure(state="disabled")
        self.token.configure(state="disabled")
        self.botao_salvar.configure(state="disabled")
        self.progresso.grid()
        self.progresso.start(12)
        self.status.configure(text="Consultando…", foreground="#526d66")
        self.escrever(f"Consultando {self.tipo.get()}: {chave}")
        threading.Thread(target=self.executar, args=(token, tipo, chave), daemon=True).start()

    def executar(self, token, tipo, chave):
        try:
            dados = consultar_asaas(token, tipo, chave)
            texto = formatar_resultado(dados).replace(token, "[token oculto]")
            self.fila.put(("sucesso", texto))
        except ConsultaSemCadastro as retorno:
            self.fila.put(("sem_cadastro", str(retorno)))
        except ConsultaInconclusiva as retorno:
            self.fila.put(("inconclusivo", str(retorno)))
        except ErroConsulta as erro:
            self.fila.put(("erro", str(erro)))
        except Exception:
            self.fila.put(("erro", "Não foi possível concluir a consulta. Feche o programa e tente novamente."))

    def receber_resultado(self):
        if self.fechado:
            return
        try:
            resultado, texto = self.fila.get_nowait()
        except queue.Empty:
            pass
        else:
            self.ocupado = False
            self.botao.configure(state="normal", text="Consultar")
            self.tipo.configure(state="readonly")
            self.chave.configure(state="normal")
            self.token.configure(state="normal")
            self.botao_salvar.configure(state="normal")
            self.progresso.stop()
            self.progresso.grid_remove()
            sem_cadastro = resultado == "sem_cadastro"
            inconclusivo = resultado == "inconclusivo"
            self.escrever(texto, sem_cadastro=sem_cadastro, inconclusivo=inconclusivo)
            self.status.configure(text=texto if sem_cadastro else "Consulta inconclusiva. Veja os detalhes abaixo." if inconclusivo else "Consulta concluída." if resultado == "sucesso" else "Consulta não concluída. Veja o motivo abaixo.",
                                  foreground=COR_SUCESSO_SUAVE if sem_cadastro else "#775d2b" if inconclusivo else "#116b55" if resultado == "sucesso" else "#a13d29")
            self.atualizar_limite(reagendar=False)
            self.chave.focus_set()
        self.janela.after(100, self.receber_resultado)

    def fechar(self):
        self.fechado = True
        self.token.configure(state="normal")
        self.token.delete(0, "end")
        self.janela.destroy()


if __name__ == "__main__":
    Aplicativo(tk.Tk()).janela.mainloop()
