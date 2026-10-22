#!/usr/bin/env python3
"""Consulta manual de uma chave Pix pelo Asaas. Python 3.9+, sem pip."""

import json
import queue
import re
import socket
import ssl
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import ttk


ENDPOINT = "https://api.asaas.com/v3/pix/addressKeys/external"
TIPOS = {"CPF": "CPF", "CNPJ": "CNPJ", "E-mail": "EMAIL",
         "Telefone": "PHONE", "Aleatória": "EVP"}
MAX_RESPOSTA = 262144


class ErroConsulta(Exception):
    """Mensagem que pode ser mostrada na interface."""


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
        400: "O Asaas não conseguiu consultar essa chave. Confira o tipo e o valor.",
        401: "Token não autorizado. Confira se ele é de produção, está válido e foi copiado inteiro.",
        403: "O Asaas negou o acesso. Confira a aprovação da conta e as permissões da API.",
        404: "O Asaas não encontrou o recurso consultado. Confira os detalhes abaixo.",
        429: "Limite de consultas ou cota atingido. Aguarde antes de tentar novamente.",
    }
    mensagem = mensagens.get(status, "O Asaas está indisponível no momento." if status >= 500 else "Não foi possível concluir a consulta.")
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
    token = token.strip()
    if not token:
        raise ErroConsulta("Cole seu token de produção do Asaas.")
    if len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ErroConsulta("O token contém espaços ou caracteres inválidos. Copie-o novamente.")
    if token.startswith("$aact_hmlg_"):
        raise ErroConsulta("Esse token é de testes (sandbox). Use um token de produção para consultar chaves reais.")
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
            raise ErroConsulta("O Asaas retornou uma resposta maior que o esperado.")
        dados = json.loads(bruto.decode("utf-8-sig"))
        if not isinstance(dados, dict) or not dados:
            raise ErroConsulta("O Asaas retornou uma resposta inesperada. Não foi possível confirmar a chave.")
        if dados.get("errors"):
            raise ErroConsulta(mensagem_http(400, dados, token))
        return dados
    except urllib.error.HTTPError as erro:
        try:
            dados = json.loads(erro.read(MAX_RESPOSTA).decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            dados = {}
        finally:
            erro.close()
        raise ErroConsulta(mensagem_http(erro.code, dados, token)) from None
    except (TimeoutError, socket.timeout):
        raise ErroConsulta("O Asaas demorou para responder. Confira a conexão e tente novamente.") from None
    except urllib.error.URLError as erro:
        if isinstance(erro.reason, ssl.SSLError):
            raise ErroConsulta("Não foi possível validar a conexão segura. Confira a data do computador e os certificados do Python.") from None
        raise ErroConsulta("Não foi possível conectar ao Asaas. Confira sua internet e tente novamente.") from None
    except (ValueError, UnicodeError):
        raise ErroConsulta("O Asaas retornou uma resposta que não foi possível ler. Tente novamente mais tarde.") from None
    except OSError:
        raise ErroConsulta("Não foi possível estabelecer a conexão segura com o Asaas.") from None


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
    return (resumo + "\n\n── Resposta completa do Asaas ──\n\n" + completo) if resumo else completo


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
        ttk.Label(conteudo, text="Uma chave por vez, direto pelo Asaas.", style="Ajuda.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 22))

        linha_token = ttk.Frame(conteudo)
        linha_token.grid(row=2, column=0, sticky="ew")
        ttk.Label(linha_token, text="Token do Asaas").pack(side="left")
        self.mostrar_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(linha_token, text="Mostrar", variable=self.mostrar_token, command=self.alternar_token).pack(side="right")
        self.token = ttk.Entry(conteudo, show="*")
        self.token.grid(row=3, column=0, sticky="ew", pady=(5, 4))
        ttk.Label(conteudo, text="Use o token de produção. Ele não será salvo.", style="Ajuda.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 17))

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
        self.token.focus_set()
        self.janela.after(100, self.receber_resultado)

    def alternar_token(self):
        self.token.configure(show="" if self.mostrar_token.get() else "*")

    def escrever(self, texto):
        self.resultado.configure(state="normal")
        self.resultado.delete("1.0", "end")
        self.resultado.insert("1.0", texto)
        self.resultado.configure(state="disabled")

    def consultar(self):
        if self.ocupado:
            return
        token = self.token.get().strip()
        tipo = TIPOS.get(self.tipo.get())
        try:
            if not token:
                self.token.focus_set()
                raise ErroConsulta("Cole seu token de produção do Asaas.")
            chave = normalizar_chave(tipo, self.chave.get())
        except ErroConsulta as erro:
            self.status.configure(text=str(erro), foreground="#a13d29")
            self.escrever("Consulta não enviada. Confira os campos acima.")
            return
        self.ocupado = True
        self.botao.configure(state="disabled", text="Consultando…")
        self.tipo.configure(state="disabled")
        self.chave.configure(state="disabled")
        self.token.configure(state="disabled")
        self.progresso.grid()
        self.progresso.start(12)
        self.status.configure(text="Consultando o Asaas…", foreground="#526d66")
        self.escrever(f"Consultando {self.tipo.get()}: {chave}")
        threading.Thread(target=self.executar, args=(token, tipo, chave), daemon=True).start()

    def executar(self, token, tipo, chave):
        try:
            dados = consultar_asaas(token, tipo, chave)
            texto = formatar_resultado(dados).replace(token, "[token oculto]")
            self.fila.put((True, texto))
        except ErroConsulta as erro:
            self.fila.put((False, str(erro)))
        except Exception:
            self.fila.put((False, "Não foi possível concluir a consulta. Feche o programa e tente novamente."))

    def receber_resultado(self):
        if self.fechado:
            return
        try:
            sucesso, texto = self.fila.get_nowait()
        except queue.Empty:
            pass
        else:
            self.ocupado = False
            self.botao.configure(state="normal", text="Consultar")
            self.tipo.configure(state="readonly")
            self.chave.configure(state="normal")
            self.token.configure(state="normal")
            self.progresso.stop()
            self.progresso.grid_remove()
            self.escrever(texto)
            self.status.configure(text="Resposta recebida do Asaas." if sucesso else "Consulta não concluída. Veja o motivo abaixo.",
                                  foreground="#116b55" if sucesso else "#a13d29")
            self.chave.focus_set()
        self.janela.after(100, self.receber_resultado)

    def fechar(self):
        self.fechado = True
        self.token.configure(state="normal")
        self.token.delete(0, "end")
        self.janela.destroy()


if __name__ == "__main__":
    Aplicativo(tk.Tk()).janela.mainloop()
