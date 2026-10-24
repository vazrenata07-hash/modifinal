#!/usr/bin/env python3
"""Consulta individual de chaves Pix, com entrada manual ou lista local."""

import configparser
import hashlib
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
from datetime import datetime
from tkinter import filedialog, ttk

from lista_pix import (ErroImportacaoLista, importar_lista, remover_linha_consultada,
                      verificar_origem)


ENDPOINT = "https://api.asaas.com/v3/pix/addressKeys/external"
TIPOS = {"CPF": "CPF", "CNPJ": "CNPJ", "E-mail": "EMAIL",
         "Telefone": "PHONE", "Aleatória": "EVP"}
MAX_RESPOSTA = 262144
COR_SUCESSO_SUAVE = "#4d8268"
FUNDO_SUCESSO_SUAVE = "#edf7ef"
MAX_CONSULTAS = 1
INTERVALO_CONSULTAS = 61
TEMPOS_PADRAO = {"manual": 61, "lista": 61}
PAUSA_PADRAO = {"ativa": False, "a_cada": 10, "duracao": 60}
FORMATO_SAIDA = "cpf_sem_pix_sucesso_v1"


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
        super().__init__(f"Aguarde {segundos} segundos para consultar novamente.")


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


def validar_tempo(valor, modo):
    texto = str(valor).strip()
    if not re.fullmatch(r"[0-9]+", texto):
        raise ErroConsulta(f"O tempo de {'consulta manual' if modo == 'manual' else 'lista automática'} deve ser um número inteiro de 1 a 86400 segundos.")
    try:
        segundos = int(texto)
    except ValueError:
        raise ErroConsulta("Informe tempos inteiros de 1 a 86400 segundos.") from None
    if not 1 <= segundos <= 86400:
        raise ErroConsulta(f"O tempo de {'consulta manual' if modo == 'manual' else 'lista automática'} deve ficar entre 1 e 86400 segundos.")
    return segundos


def tempos_configuracao(configuracao):
    return {modo: validar_tempo(configuracao.get("tempos", modo, fallback=str(padrao)), modo)
            for modo, padrao in TEMPOS_PADRAO.items()}


def carregar_tempos(caminho=None):
    destino = Path(caminho) if caminho is not None else caminho_cache()
    return tempos_configuracao(ler_configuracao(destino))


def inteiro_pausa(valor, maximo, campo):
    texto = str(valor).strip()
    if not re.fullmatch(r"[0-9]+", texto):
        raise ErroConsulta(f"{campo}: informe um número inteiro de 1 a {maximo}.")
    try:
        numero = int(texto)
    except ValueError:
        raise ErroConsulta(f"{campo}: informe um número inteiro de 1 a {maximo}.") from None
    if not 1 <= numero <= maximo:
        raise ErroConsulta(f"{campo}: informe um número inteiro de 1 a {maximo}.")
    return numero


def validar_opcoes_pausa(opcoes, modo):
    nome = "Manual" if modo == "manual" else "Lista"
    if not isinstance(opcoes, dict):
        raise ErroConsulta(f"As opções de pausa extra de {nome} não são válidas.")
    ativa = opcoes.get("ativa", False)
    if not isinstance(ativa, bool):
        raise ErroConsulta(f"A opção de pausa extra de {nome} não é válida.")
    return {"ativa": ativa,
            "a_cada": inteiro_pausa(opcoes.get("a_cada", 10), 100000, f"{nome} — a cada quantas consultas"),
            "duracao": inteiro_pausa(opcoes.get("duracao", 60), 86400, f"{nome} — pausa extra em segundos")}


def opcoes_pausa_configuracao(configuracao, modo):
    secao = "pausa_" + modo
    valor_ativa = configuracao.get(secao, "ativa", fallback="0").strip().lower()
    if valor_ativa not in ("0", "1", "false", "true", "no", "yes", "off", "on"):
        raise ErroConsulta("A ativação da pausa extra no cache.ini não é válida. Corrija-a em Configurações.")
    return validar_opcoes_pausa({"ativa": valor_ativa in ("1", "true", "yes", "on"),
                                "a_cada": configuracao.get(secao, "a_cada", fallback="10"),
                                "duracao": configuracao.get(secao, "duracao", fallback="60")}, modo)


def estado_pausa_configuracao(configuracao, modo):
    opcoes = opcoes_pausa_configuracao(configuracao, modo)
    secao = "pausa_" + modo
    try:
        contador_texto = configuracao.get(secao, "contador", fallback="0").strip()
        if not re.fullmatch(r"[0-9]+", contador_texto):
            raise ValueError
        contador = int(contador_texto)
        pausa_ate = float(configuracao.get(secao, "pausa_ate", fallback="0"))
        marcador_texto = configuracao.get(secao, "marcador", fallback="").strip()
        marcador = float(marcador_texto) if marcador_texto else None
        if not 0 <= contador < opcoes["a_cada"] or not math.isfinite(pausa_ate) or pausa_ate < 0:
            raise ValueError
        if marcador is not None and (not math.isfinite(marcador) or marcador < 0):
            raise ValueError
    except (ValueError, TypeError, configparser.Error):
        raise ErroConsulta("O estado da pausa extra no cache.ini é inválido. Altere a opção correspondente em Configurações para reiniciá-la.") from None
    return dict(opcoes, contador=contador, pausa_ate=pausa_ate, marcador=marcador)


def salvar_tempos(manual, lista, caminho=None, *, pausas=None):
    tempos = {"manual": validar_tempo(manual, "manual"), "lista": validar_tempo(lista, "lista")}
    novas_pausas = {}
    if pausas is not None:
        if not isinstance(pausas, dict) or any(modo not in TEMPOS_PADRAO for modo in pausas):
            raise ErroConsulta("As opções de pausa extra não são válidas.")
        novas_pausas = {modo: validar_opcoes_pausa(opcoes, modo) for modo, opcoes in pausas.items()}
    destino = Path(caminho) if caminho is not None else caminho_cache()
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        if not configuracao.has_section("tempos"):
            configuracao.add_section("tempos")
        for modo, segundos in tempos.items():
            configuracao.set("tempos", modo, str(segundos))
        for modo, opcoes in novas_pausas.items():
            try:
                antigas = opcoes_pausa_configuracao(configuracao, modo)
            except ErroConsulta:
                antigas = None
            secao = "pausa_" + modo
            if not configuracao.has_section(secao):
                configuracao.add_section(secao)
            configuracao.set(secao, "ativa", "1" if opcoes["ativa"] else "0")
            configuracao.set(secao, "a_cada", str(opcoes["a_cada"]))
            configuracao.set(secao, "duracao", str(opcoes["duracao"]))
            if antigas != opcoes:
                configuracao.set(secao, "contador", "0")
                configuracao.set(secao, "pausa_ate", "0")
                configuracao.set(secao, "marcador", "")
        gravar_configuracao(configuracao, destino)
    return tempos


def historico_ativo(configuracao, agora):
    try:
        horarios = json.loads(configuracao.get("limite", "timestamps", fallback="[]"))
        if not isinstance(horarios, list) or len(horarios) > 100:
            raise ValueError
        if any(isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(h) or h < 0 for h in horarios):
            raise ValueError
        # Preserve o último envio mesmo depois de seu intervalo expirar.
        # Assim um tempo maior pode ser aplicado posteriormente sem perder a referência.
        return sorted(float(h) for h in horarios)[-1:]
    except (ValueError, TypeError, configparser.Error):
        raise ErroConsulta("O histórico de consultas do cache.ini é inválido. Confira o arquivo antes de continuar.") from None


def espera_historico(horarios, agora, intervalo=INTERVALO_CONSULTAS):
    if not horarios:
        return 0
    return max(0, math.ceil(horarios[-1] + intervalo - agora))


def detalhes_espera(caminho=None, agora=None, modo="manual"):
    destino = Path(caminho) if caminho is not None else caminho_cache()
    agora = time.time() if agora is None else agora
    configuracao = ler_configuracao(destino)
    if modo not in TEMPOS_PADRAO:
        raise ErroConsulta("O modo de consulta não é válido.")
    tempos = tempos_configuracao(configuracao)
    base = espera_historico(historico_ativo(configuracao, agora), agora, tempos[modo])
    pausa = estado_pausa_configuracao(configuracao, modo)
    extra = max(0, math.ceil(pausa["pausa_ate"] - agora)) if pausa["ativa"] else 0
    return {"total": max(base, extra), "base": base, "extra": extra,
            "extra_ativa": extra > base, "intervalo": tempos[modo],
            "pausa_ativa": pausa["ativa"], "a_cada": pausa["a_cada"],
            "duracao_extra": pausa["duracao"], "contador": pausa["contador"],
            "ciclo_exibido": pausa["a_cada"] if extra > 0 else pausa["contador"]}


def segundos_ate_liberar(caminho=None, agora=None, modo="manual"):
    return detalhes_espera(caminho=caminho, agora=agora, modo=modo)["total"]


def resumo_temporizacao(detalhes):
    texto = f"Intervalo salvo: {detalhes['intervalo']} segundos; "
    if detalhes["pausa_ativa"]:
        texto += (f"pausa extra: {detalhes['duracao_extra']} segundos a cada {detalhes['a_cada']} consultas; "
                  f"ciclo atual: {detalhes['ciclo_exibido']}/{detalhes['a_cada']}.")
    else:
        texto += "pausa extra desativada."
    return texto


def registrar_consulta(caminho=None, agora=None, modo="manual"):
    """Persiste a tentativa antes de enviar; não salva o token digitado."""
    destino = Path(caminho) if caminho is not None else caminho_cache()
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        if modo not in TEMPOS_PADRAO:
            raise ErroConsulta("O modo de consulta não é válido.")
        tempos = tempos_configuracao(configuracao)
        pausa = estado_pausa_configuracao(configuracao, modo)
        agora = time.time() if agora is None else agora
        horarios = historico_ativo(configuracao, agora)
        base = espera_historico(horarios, agora, tempos[modo])
        extra = max(0, math.ceil(pausa["pausa_ate"] - agora)) if pausa["ativa"] else 0
        espera = max(base, extra)
        if espera:
            raise LimiteConsultas(espera)
        if not configuracao.has_section("limite"):
            configuracao.add_section("limite")
        configuracao.set("limite", "timestamps", json.dumps([agora]))
        marcador = None
        if pausa["ativa"]:
            secao = "pausa_" + modo
            if not configuracao.has_section(secao):
                configuracao.add_section(secao)
            contador = pausa["contador"] + 1
            if contador >= pausa["a_cada"]:
                contador = 0
                configuracao.set(secao, "pausa_ate", repr(agora + tempos[modo] + pausa["duracao"]))
                configuracao.set(secao, "marcador", repr(agora))
                marcador = {"modo": modo, "envio": agora}
            configuracao.set(secao, "contador", str(contador))
        gravar_configuracao(configuracao, destino)
        return marcador


def finalizar_pausa_extra(marcador, caminho=None, agora=None):
    if marcador is None:
        return
    modo = marcador["modo"]
    destino = Path(caminho) if caminho is not None else caminho_cache()
    agora = time.time() if agora is None else agora
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        pausa = estado_pausa_configuracao(configuracao, modo)
        if not pausa["ativa"] or pausa["marcador"] != marcador["envio"]:
            return
        secao = "pausa_" + modo
        configuracao.set(secao, "pausa_ate", repr(max(pausa["pausa_ate"], agora + pausa["duracao"])))
        configuracao.set(secao, "marcador", "")
        gravar_configuracao(configuracao, destino)


def chave_associacao_lista(origem):
    canonico = os.path.normcase(str(Path(origem).resolve()))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def identidade_ciclo_lista(origem):
    try:
        verificar_origem(origem)
    except ErroImportacaoLista as erro:
        raise ErroConsulta(str(erro)) from None
    canonico = os.path.normcase(str(origem.caminho.resolve()))
    resumo = hashlib.sha256(origem.esperado).hexdigest()
    return canonico, resumo


def preparar_ciclo_lista(origem, caminho=None):
    """Uma lista nova inicia seu ciclo; o mesmo TXT pendente o continua."""
    canonico, resumo = identidade_ciclo_lista(origem)
    destino = Path(caminho) if caminho is not None else caminho_cache()
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        origem_salva = configuracao.get("pausa_lista", "origem", fallback="")
        resumo_salvo = configuracao.get("pausa_lista", "hash_pendente", fallback="")
        if origem_salva == canonico and resumo_salvo == resumo:
            return False
        if not configuracao.has_section("pausa_lista"):
            configuracao.add_section("pausa_lista")
        configuracao.set("pausa_lista", "contador", "0")
        configuracao.set("pausa_lista", "pausa_ate", "0")
        configuracao.set("pausa_lista", "marcador", "")
        configuracao.set("pausa_lista", "origem", canonico)
        configuracao.set("pausa_lista", "hash_pendente", resumo)
        gravar_configuracao(configuracao, destino)
    return True


def sincronizar_ciclo_lista(origem, caminho=None):
    """Atualize só o hash após remoção; preserve o ciclo e a pausa em curso."""
    canonico, resumo = identidade_ciclo_lista(origem)
    destino = Path(caminho) if caminho is not None else caminho_cache()
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        if configuracao.get("pausa_lista", "origem", fallback="") != canonico:
            raise ErroConsulta("A lista associada ao contador foi alterada. O resultado foi mantido; confira o cache.ini antes de continuar.")
        if configuracao.get("pausa_lista", "hash_pendente", fallback="") == resumo:
            return
        configuracao.set("pausa_lista", "hash_pendente", resumo)
        gravar_configuracao(configuracao, destino)


def carregar_saida_associada(origem):
    configuracao = ler_configuracao(caminho_cache())
    valor = configuracao.get("listas", chave_associacao_lista(origem), fallback="")
    if not valor:
        return None
    try:
        dados = json.loads(valor)
        saida = Path(dados["saida"])
        if not isinstance(dados["saida"], str) or saida.resolve() == Path(origem).resolve():
            raise ValueError
        formato = dados.get("formato")
    except (ValueError, TypeError, KeyError):
        raise ErroConsulta("A associação do TXT com o resultado no cache.ini é inválida. Confira o arquivo antes de continuar.") from None
    try:
        if not saida.exists():
            return saida
    except OSError:
        raise ErroConsulta("Não foi possível acessar o resultado anterior. O arquivo foi preservado; confira as permissões.") from None
    if formato == FORMATO_SAIDA:
        ler_cpfs_saida_limpa(saida)
        return saida
    if formato not in (None, "", "cpf_sem_pix_v1"):
        raise ErroConsulta("O formato do resultado anterior não é reconhecido. O arquivo foi preservado; confira-o antes de continuar.")
    cpfs, ja_formatado = recuperar_cpfs_legados(saida)
    if ja_formatado:
        salvar_saida_associada(origem, saida)
        return saida
    nova_saida = criar_saida_resultados(origem)
    acrescentar_saida_resultados(nova_saida, cpfs)
    salvar_saida_associada(origem, nova_saida)
    return nova_saida


def salvar_saida_associada(origem, saida):
    destino = caminho_cache()
    with bloquear_cache(destino):
        configuracao = ler_configuracao(destino)
        if not configuracao.has_section("listas"):
            configuracao.add_section("listas")
        dados = {"origem": str(Path(origem).resolve()), "saida": str(Path(saida).resolve()), "formato": FORMATO_SAIDA}
        configuracao.set("listas", chave_associacao_lista(origem), json.dumps(dados, ensure_ascii=False))
        gravar_configuracao(configuracao, destino)


def criar_saida_resultados(origem):
    nome = "resultados_pix_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".txt"
    destino = caminho_cache().parent / nome
    if destino.resolve() == Path(origem).resolve():
        raise ErroConsulta("O arquivo de resultados precisa ser diferente do TXT original.")
    try:
        descritor = os.open(str(destino), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as arquivo:
            arquivo.flush()
            os.fsync(arquivo.fileno())
    except OSError:
        raise ErroConsulta("Não foi possível criar o TXT de resultados. Confira a permissão de gravação na pasta do programa.") from None
    return destino


def ler_texto_resultado(caminho):
    try:
        return Path(caminho).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except (OSError, UnicodeError):
        raise ErroConsulta("Não foi possível ler o resultado anterior. O arquivo foi preservado; confira-o antes de continuar.") from None


def ler_cpfs_saida_limpa(caminho):
    linhas = ler_texto_resultado(caminho).splitlines()
    if any(not re.fullmatch(r"[0-9]{11} sucesso", linha) for linha in linhas):
        raise ErroConsulta("O TXT de saída contém um formato diferente de CPF seguido de sucesso. A lista foi pausada para preservar o arquivo.")
    return [linha[:11] for linha in linhas]


def recuperar_cpfs_legados(caminho):
    texto = ler_texto_resultado(caminho)
    linhas = texto.splitlines()
    if all(re.fullmatch(r"[0-9]{11}(?: sucesso)?", linha) for linha in linhas):
        return [linha[:11] for linha in linhas], all(linha.endswith(" sucesso") for linha in linhas)
    separador_cabecalho = "\n" + "=" * 60 + "\n\n"
    partes = texto.split(separador_cabecalho, 1)
    if len(partes) != 2 or not re.fullmatch(r"Consultar Pix — resultados da lista\nCriado em: [^\n]+\nOrigem: [^\n]+", partes[0]):
        raise ErroConsulta("O resultado anterior não corresponde ao relatório conhecido. Ele foi preservado; a lista não será iniciada.")
    corpo = partes[1]
    separador = "\n\n" + "-" * 60 + "\n\n"
    if corpo and not corpo.endswith(separador):
        raise ErroConsulta("O relatório anterior está incompleto. Ele foi preservado; confira o arquivo antes de continuar.")
    blocos = corpo.split(separador)[:-1] if corpo else []
    cpfs = []
    padrao = re.compile(r"Hora: (?P<hora>[^\n]+)\nLinha original: (?P<linha>[0-9]+)\nChave: (?P<chave>[^\n]+)\nTipo: (?P<tipo>[^\n]+)\nStatus: (?P<status>[^\n]+)\n\n(?P<texto>[\s\S]*)")
    estados = {"Dados recebidos", "Sem Pix cadastrado", "Inconclusivo", "Erro na consulta", "Formato inválido", "Consulta concluída"}
    for bloco in blocos:
        registro = padrao.fullmatch(bloco)
        if registro is None:
            raise ErroConsulta("Há um registro ilegível no relatório anterior. O arquivo foi preservado; a lista não será iniciada.")
        dados = registro.groupdict()
        try:
            datetime.fromisoformat(dados["hora"])
            valido = int(dados["linha"]) > 0 and dados["tipo"] in TIPOS.values() and dados["status"] in estados
        except ValueError:
            valido = False
        if not valido:
            raise ErroConsulta("Há um registro fora do formato conhecido no relatório anterior. O arquivo foi preservado.")
        if dados["tipo"] == "CPF" and dados["status"] == "Sem Pix cadastrado":
            if not re.fullmatch(r"[0-9]{11}", dados["chave"]) or dados["texto"] != "Sucesso, CPF sem Pix cadastrado.":
                raise ErroConsulta("Um resultado negativo do relatório anterior não pôde ser confirmado. O arquivo foi preservado.")
            cpfs.append(dados["chave"])
    return cpfs, False


def acrescentar_saida_resultados(caminho, cpfs):
    cpfs = tuple(cpfs)
    if any(not re.fullmatch(r"[0-9]{11}", cpf) for cpf in cpfs):
        raise ErroConsulta("O resultado não contém um CPF com 11 dígitos. A linha original não será removida.")
    if not cpfs:
        return
    ler_cpfs_saida_limpa(caminho)
    existente = ler_texto_resultado(caminho)
    quebra = "\n" if existente and not existente.endswith("\n") else ""
    bloco = quebra + "".join(cpf + " sucesso\n" for cpf in cpfs)
    try:
        descritor = os.open(str(caminho), os.O_WRONLY | os.O_APPEND)
        with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(bloco)
            arquivo.flush()
            os.fsync(arquivo.fileno())
    except OSError:
        raise ErroConsulta("Não foi possível acrescentar o resultado ao TXT de saída. A lista foi pausada; a linha original não será removida.") from None


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
        self.importando = False
        self.fila_importacao = queue.Queue()
        self.registros_lista = {}
        self.item_em_consulta = None
        self.lista_ativa = False
        self.lista_finalizados = set()
        self.agendamento_lista = None
        self.consulta_automatica_em_curso = False
        self.token_lista = ""
        self.tipo_lista_capturado = "CPF"
        self.origem_lista = None
        self.arquivo_resultados = None
        self.associacao_persistida = False
        self.erro_saida_associada = None
        self.tipo_em_consulta = "CPF"
        self.pendencia_resultado = None
        self.janela_configuracoes = None
        self.botao_salvar_config = None
        self.marcador_pausa_em_consulta = None
        self.pendencias_pausa = {}
        janela.title("Consultar Pix")
        janela.geometry("720x850")
        janela.minsize(600, 760)
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
        cabecalho = ttk.Frame(conteudo)
        cabecalho.grid(row=0, column=0, sticky="ew")
        ttk.Label(cabecalho, text="Consultar Pix", style="Titulo.TLabel").pack(side="left")
        ttk.Button(cabecalho, text="Configurações", command=self.abrir_configuracoes).pack(side="right")
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

        self.abas = ttk.Notebook(conteudo)
        self.abas.grid(row=5, column=0, sticky="ew")
        self.aba_manual = ttk.Frame(self.abas, padding=12)
        self.aba_lista = ttk.Frame(self.abas, padding=12)
        self.abas.add(self.aba_manual, text="Manual")
        self.abas.add(self.aba_lista, text="Lista")
        self.aba_manual.columnconfigure(0, weight=1)
        linha = ttk.Frame(self.aba_manual)
        linha.grid(row=0, column=0, sticky="ew")
        linha.columnconfigure(1, weight=1)
        ttk.Label(linha, text="Tipo").grid(row=0, column=0, sticky="w")
        ttk.Label(linha, text="Chave Pix").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.tipo = ttk.Combobox(linha, values=list(TIPOS), state="readonly", width=12)
        self.tipo.set("CPF")
        self.tipo.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.chave = ttk.Entry(linha)
        self.chave.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(5, 0))
        self.montar_aba_lista()
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
        self.janela.after(100, self.receber_importacao)
        self.abas.bind("<<NotebookTabChanged>>", lambda evento: self.atualizar_limite(reagendar=False))
        self.atualizar_limite()

    def montar_aba_lista(self):
        self.aba_lista.columnconfigure(0, weight=1)
        barra = ttk.Frame(self.aba_lista)
        barra.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.botao_abrir_lista = ttk.Button(barra, text="Abrir TXT", command=self.abrir_lista)
        self.botao_abrir_lista.pack(side="left")
        ttk.Label(barra, text="Tipo").pack(side="left", padx=(15, 5))
        self.tipo_lista = ttk.Combobox(barra, values=("CPF", "Telefone"), state="readonly", width=10)
        self.tipo_lista.set("CPF")
        self.tipo_lista.pack(side="left")
        self.botao_lista = ttk.Button(barra, text="Iniciar lista", command=self.alternar_lista)
        self.botao_lista.pack(side="right", padx=(8, 0))
        quadro = ttk.Frame(self.aba_lista)
        quadro.grid(row=1, column=0, sticky="ew")
        quadro.columnconfigure(0, weight=1)
        self.lista = ttk.Treeview(quadro, columns=("linha", "numero", "resultado"), show="headings", selectmode="browse", height=5)
        self.lista.heading("linha", text="Linha")
        self.lista.heading("numero", text="11 dígitos identificados")
        self.lista.heading("resultado", text="Resultado")
        self.lista.column("linha", width=55, minwidth=45, stretch=False)
        self.lista.column("numero", width=190, minwidth=145, stretch=False)
        self.lista.column("resultado", width=220, minwidth=140)
        self.lista.grid(row=0, column=0, sticky="ew")
        rolagem = ttk.Scrollbar(quadro, orient="vertical", command=self.lista.yview)
        rolagem.grid(row=0, column=1, sticky="ns")
        self.lista.configure(yscrollcommand=rolagem.set)
        self.resumo_lista = ttk.Label(self.aba_lista, text="Abra um TXT e clique em Iniciar lista. O intervalo pode ser ajustado em Configurações.", style="Ajuda.TLabel", wraplength=600)
        self.resumo_lista.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.progresso_lista = ttk.Label(self.aba_lista, text="0/0 processadas", style="Ajuda.TLabel")
        self.progresso_lista.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.rotulo_saida = ttk.Label(self.aba_lista, text="O TXT de CPFs sem Pix será criado ao iniciar a lista.", style="Ajuda.TLabel", wraplength=600)
        self.rotulo_saida.grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.temporizacao_lista = ttk.Label(self.aba_lista, text="", style="Ajuda.TLabel", wraplength=600)
        self.temporizacao_lista.grid(row=5, column=0, sticky="w", pady=(4, 0))

    def modo_lista(self):
        return hasattr(self, "abas") and self.abas.select() == str(self.aba_lista)

    def abrir_configuracoes(self):
        if self.janela_configuracoes is not None and self.janela_configuracoes.winfo_exists():
            self.janela_configuracoes.lift()
            self.janela_configuracoes.focus_set()
            return
        try:
            configuracao = ler_configuracao(caminho_cache())
        except ErroConsulta as erro:
            self.status.configure(text=str(erro), foreground="#a13d29")
            return
        dialogo = tk.Toplevel(self.janela)
        self.janela_configuracoes = dialogo
        dialogo.title("Configurações")
        dialogo.transient(self.janela)
        dialogo.resizable(False, False)
        quadro = ttk.Frame(dialogo, padding=20)
        quadro.pack(fill="both", expand=True)
        quadro.columnconfigure(1, weight=1)
        manual = tk.StringVar(value=configuracao.get("tempos", "manual", fallback=str(TEMPOS_PADRAO["manual"])))
        lista = tk.StringVar(value=configuracao.get("tempos", "lista", fallback=str(TEMPOS_PADRAO["lista"])))
        ttk.Label(quadro, text="Consulta manual (segundos)").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        campo_manual = ttk.Entry(quadro, textvariable=manual, width=12)
        campo_manual.grid(row=0, column=1, sticky="ew", pady=(0, 10))
        ttk.Label(quadro, text="Lista automática (segundos)").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(0, 12))
        ttk.Entry(quadro, textvariable=lista, width=12).grid(row=1, column=1, sticky="ew", pady=(0, 12))
        variaveis_pausas = {}
        for indice, (modo, nome) in enumerate((("manual", "Consulta manual"), ("lista", "Lista automática")), start=2):
            grupo = ttk.LabelFrame(quadro, text=nome + " — pausa extra", padding=10)
            grupo.grid(row=indice, column=0, columnspan=2, sticky="ew", pady=(0, 12))
            grupo.columnconfigure(1, weight=1)
            secao = "pausa_" + modo
            ativa = tk.BooleanVar(value=configuracao.get(secao, "ativa", fallback="0").strip().lower() in ("1", "true", "yes", "on"))
            a_cada = tk.StringVar(value=configuracao.get(secao, "a_cada", fallback=str(PAUSA_PADRAO["a_cada"])))
            duracao = tk.StringVar(value=configuracao.get(secao, "duracao", fallback=str(PAUSA_PADRAO["duracao"])))
            ttk.Label(grupo, text="A cada (consultas)").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(5, 5))
            campo_quantidade = ttk.Entry(grupo, textvariable=a_cada, width=12)
            campo_quantidade.grid(row=1, column=1, sticky="ew", pady=(5, 5))
            ttk.Label(grupo, text="Pausa extra (segundos)").grid(row=2, column=0, sticky="w", padx=(0, 12))
            campo_duracao = ttk.Entry(grupo, textvariable=duracao, width=12)
            campo_duracao.grid(row=2, column=1, sticky="ew")

            def atualizar_campos(variavel=ativa, quantidade=campo_quantidade, tempo=campo_duracao):
                estado = "normal" if variavel.get() else "disabled"
                quantidade.configure(state=estado)
                tempo.configure(state=estado)

            ttk.Checkbutton(grupo, text="Ativar pausa extra", variable=ativa, command=atualizar_campos).grid(row=0, column=0, columnspan=2, sticky="w")
            atualizar_campos()
            variaveis_pausas[modo] = {"ativa": ativa, "a_cada": a_cada, "duracao": duracao}
            try:
                resumo_salvo = resumo_temporizacao(detalhes_espera(modo=modo))
            except ErroConsulta:
                resumo_salvo = "Corrija os valores salvos para visualizar a temporização efetiva."
            ttk.Label(grupo, text=resumo_salvo, style="Ajuda.TLabel", wraplength=420).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(quadro, text="Informe intervalos e pausas de 1 a 86400 segundos.\nContagem a partir do último envio, inclusive ao trocar modo.\nEm cada modo: a cada X envios, acrescentar Y segundos ao intervalo.\nManual: ciclo mantido entre sessões.\nLista: continua no mesmo TXT pendente; uma nova lista começa em zero.", style="Ajuda.TLabel", wraplength=440).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 10))
        mensagem = ttk.Label(quadro, text="", foreground="#a13d29", wraplength=440)
        mensagem.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 12))
        try:
            tempos_configuracao(configuracao)
            for modo in TEMPOS_PADRAO:
                opcoes_pausa_configuracao(configuracao, modo)
        except ErroConsulta as erro:
            mensagem.configure(text=str(erro))

        def fechar(evento=None):
            self.janela_configuracoes = None
            self.botao_salvar_config = None
            dialogo.destroy()
            return "break"

        def salvar(evento=None):
            if self.ocupado:
                mensagem.configure(text="Aguarde a consulta em andamento terminar antes de salvar os tempos.")
                return "break"
            try:
                pausas = {modo: {"ativa": campos["ativa"].get(), "a_cada": campos["a_cada"].get(),
                                 "duracao": campos["duracao"].get()} for modo, campos in variaveis_pausas.items()}
                salvar_tempos(manual.get(), lista.get(), pausas=pausas)
            except ErroConsulta as erro:
                mensagem.configure(text=str(erro))
                return "break"
            fechar()
            self.status.configure(text="Tempos salvos nas configurações.", foreground=COR_SUCESSO_SUAVE)
            self.atualizar_limite(reagendar=False)
            if self.lista_ativa:
                self.agendar_proximo_item()
            return "break"

        botoes = ttk.Frame(quadro)
        botoes.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(botoes, text="Cancelar", command=fechar).pack(side="left", padx=(0, 8))
        self.botao_salvar_config = ttk.Button(botoes, text="Salvar", command=salvar,
                                            state="disabled" if self.ocupado else "normal")
        self.botao_salvar_config.pack(side="left")
        dialogo.protocol("WM_DELETE_WINDOW", fechar)
        dialogo.bind("<Return>", salvar)
        dialogo.bind("<Escape>", fechar)
        campo_manual.focus_set()

    def abrir_lista(self):
        if self.ocupado or self.importando or self.lista_ativa:
            return
        if self.pendencia_resultado is not None:
            self.status.configure(text="Há um resultado aguardando conclusão local. Corrija o arquivo indicado e clique em Iniciar lista antes de importar outro TXT.", foreground="#a13d29")
            return
        caminho = filedialog.askopenfilename(title="Abrir lista TXT", filetypes=[("Arquivo TXT", "*.txt")])
        if not caminho:
            return
        self.importando = True
        self.botao_abrir_lista.configure(state="disabled")
        self.botao_lista.configure(state="disabled")
        self.resumo_lista.configure(text="Lendo o arquivo localmente…")
        threading.Thread(target=self.executar_importacao, args=(caminho,), daemon=True).start()

    def executar_importacao(self, caminho):
        try:
            self.fila_importacao.put((True, importar_lista(caminho)))
        except ErroImportacaoLista as erro:
            self.fila_importacao.put((False, str(erro)))
        except Exception:
            self.fila_importacao.put((False, "Não foi possível importar o arquivo. Confira o formato e tente novamente."))

    def receber_importacao(self):
        if self.fechado:
            return
        try:
            sucesso, retorno = self.fila_importacao.get_nowait()
        except queue.Empty:
            pass
        else:
            self.importando = False
            self.botao_abrir_lista.configure(state="disabled" if self.ocupado else "normal")
            if sucesso:
                self.lista.delete(*self.lista.get_children())
                self.registros_lista.clear()
                self.lista_finalizados.clear()
                self.origem_lista = retorno.origem
                self.arquivo_resultados = None
                self.associacao_persistida = False
                self.erro_saida_associada = None
                erro_ciclo = None
                try:
                    preparar_ciclo_lista(self.origem_lista)
                except ErroConsulta as erro:
                    erro_ciclo = str(erro)
                try:
                    anterior = carregar_saida_associada(self.origem_lista.caminho)
                except ErroConsulta as erro:
                    self.erro_saida_associada = str(erro)
                    self.rotulo_saida.configure(text=str(erro))
                else:
                    if anterior is not None and anterior.is_file():
                        self.arquivo_resultados = anterior
                        self.associacao_persistida = True
                        self.rotulo_saida.configure(text="Continuar acrescentando em: " + str(anterior))
                    elif anterior is not None:
                        self.rotulo_saida.configure(text="O resultado anterior não foi encontrado. Ao iniciar, será criado um novo TXT sem sobrescrever outros arquivos.")
                    else:
                        self.rotulo_saida.configure(text="O TXT de CPFs sem Pix será criado ao iniciar a lista.")
                for indice, registro in enumerate(retorno.registros):
                    item = f"linha_{indice}"
                    self.registros_lista[item] = registro
                    self.lista.insert("", "end", iid=item, values=(registro.linha, registro.numero, "Não consultado"))
                self.resumo_lista.configure(text=f"{len(retorno.registros)} linhas identificadas. Ignoradas: {retorno.ambiguas} ambíguas e {retorno.sem_numero} sem conjunto de 11 dígitos. Clique em Iniciar lista.")
                self.atualizar_progresso_lista()
                if erro_ciclo:
                    self.status.configure(text=erro_ciclo, foreground="#a13d29")
                    self.atualizar_progresso_lista("Corrija o cache ou o TXT antes de iniciar")
            else:
                self.resumo_lista.configure(text=retorno)
            self.atualizar_controles_lista()
        self.janela.after(100, self.receber_importacao)

    def preparar_saida_lista(self):
        if self.erro_saida_associada:
            raise ErroConsulta(self.erro_saida_associada)
        if self.origem_lista is None:
            raise ErroConsulta("Importe o TXT original antes de consultar a lista.")
        try:
            verificar_origem(self.origem_lista)
        except ErroImportacaoLista as erro:
            raise ErroConsulta(str(erro)) from None
        preparar_ciclo_lista(self.origem_lista)
        if self.arquivo_resultados is None:
            self.arquivo_resultados = criar_saida_resultados(self.origem_lista.caminho)
            self.associacao_persistida = False
        try:
            descritor = os.open(str(self.arquivo_resultados), os.O_WRONLY | os.O_APPEND)
            os.close(descritor)
        except OSError:
            raise ErroConsulta("O TXT de resultados não está disponível para continuação. Confira o arquivo ou reimporte o TXT original para criar uma nova saída.") from None
        ler_cpfs_saida_limpa(self.arquivo_resultados)
        if not self.associacao_persistida:
            salvar_saida_associada(self.origem_lista.caminho, self.arquivo_resultados)
            self.associacao_persistida = True
        self.rotulo_saida.configure(text="CPFs sem Pix: " + str(self.arquivo_resultados))

    def salvar_resultado_lista(self, item, tipo, status, texto):
        registro = self.registros_lista[item]
        acrescentar_saida_resultados(self.arquivo_resultados, (registro.numero,))

    def concluir_resultado_pendente(self):
        pendencia = self.pendencia_resultado
        if pendencia is None:
            return
        item = pendencia["item"]
        if not pendencia["saida_gravada"]:
            if pendencia["resultado"] == "sem_cadastro" and pendencia["tipo"] == "CPF":
                self.salvar_resultado_lista(item, pendencia["tipo"], pendencia["status"], pendencia["texto"])
            pendencia["saida_gravada"] = True
        if pendencia["resultado"] in ("sucesso", "sem_cadastro"):
            remover_linha_consultada(self.origem_lista, self.registros_lista[item].linha)
            sincronizar_ciclo_lista(self.origem_lista)
        self.lista_finalizados.add(item)
        self.lista.set(item, "resultado", pendencia["status"])
        self.pendencia_resultado = None

    def resolver_pausa_pendente(self, modo):
        pendencia = self.pendencias_pausa.get(modo)
        if pendencia is None:
            return
        finalizar_pausa_extra(pendencia, agora=pendencia["resposta_em"])
        self.pendencias_pausa.pop(modo, None)

    def atualizar_progresso_lista(self, complemento=""):
        total = len(self.registros_lista)
        concluidos = len(self.lista_finalizados.intersection(self.registros_lista))
        texto = f"{concluidos}/{total} processadas"
        if complemento:
            texto += " · " + complemento
        self.progresso_lista.configure(text=texto)

    def atualizar_controles_lista(self):
        travado = self.ocupado or self.lista_ativa
        self.token.configure(state="disabled" if travado else "normal")
        self.botao_salvar.configure(state="disabled" if travado else "normal")
        self.tipo.configure(state="disabled" if travado else "readonly")
        self.chave.configure(state="disabled" if travado else "normal")
        self.tipo_lista.configure(state="disabled" if travado else "readonly")
        self.botao_abrir_lista.configure(state="disabled" if travado or self.importando else "normal")
        self.botao_lista.configure(text="Pausar" if self.lista_ativa else "Iniciar lista",
                                  state="normal" if self.lista_ativa or not self.ocupado and not self.importando else "disabled")
        if self.botao_salvar_config is not None:
            self.botao_salvar_config.configure(state="disabled" if self.ocupado else "normal")
        self.atualizar_limite(reagendar=False)

    def alternar_lista(self):
        if self.lista_ativa:
            self.pausar_lista("Pausada. A consulta em andamento será concluída." if self.ocupado else "Pausada.")
            return
        if self.ocupado or self.importando:
            self.status.configure(text="Aguarde a operação em andamento terminar.", foreground="#775d2b")
            return
        if not self.registros_lista:
            self.status.configure(text="Abra um arquivo TXT antes de iniciar a lista.", foreground="#775d2b")
            return
        if self.pendencia_resultado is not None:
            try:
                self.concluir_resultado_pendente()
            except (ErroConsulta, ErroImportacaoLista) as erro:
                self.pausar_lista("Pausada: conclusão local pendente")
                self.status.configure(text=str(erro), foreground="#a13d29")
                return
        try:
            self.resolver_pausa_pendente("lista")
        except ErroConsulta as erro:
            self.pausar_lista("Pausada: atualização da pausa extra pendente")
            self.status.configure(text=str(erro), foreground="#a13d29")
            return
        if all(item in self.lista_finalizados for item in self.registros_lista):
            self.atualizar_progresso_lista("Lista concluída")
            self.status.configure(text="Esta lista já foi processada. Abra um TXT para iniciar uma nova lista.", foreground=COR_SUCESSO_SUAVE)
            return
        try:
            self.token_lista = validar_token(self.token.get())
            self.tipo_lista_capturado = TIPOS[self.tipo_lista.get()]
            preparar_ciclo_lista(self.origem_lista)
            segundos_ate_liberar(modo="lista")
            self.preparar_saida_lista()
        except (ErroConsulta, KeyError) as erro:
            self.status.configure(text=str(erro) if isinstance(erro, ErroConsulta) else "Selecione o tipo da lista.", foreground="#a13d29")
            return
        self.lista_ativa = True
        self.atualizar_controles_lista()
        self.atualizar_progresso_lista("Em andamento")
        self.agendar_proximo_item()

    def pausar_lista(self, motivo="Pausada."):
        self.lista_ativa = False
        if self.agendamento_lista is not None:
            self.janela.after_cancel(self.agendamento_lista)
            self.agendamento_lista = None
        self.token_lista = ""
        self.atualizar_progresso_lista(motivo)
        self.atualizar_controles_lista()

    def agendar_proximo_item(self):
        if self.fechado or not self.lista_ativa or self.ocupado:
            return
        if self.agendamento_lista is not None:
            self.janela.after_cancel(self.agendamento_lista)
        self.agendamento_lista = self.janela.after(1, self.proximo_item_lista)

    def proximo_item_lista(self):
        self.agendamento_lista = None
        if self.fechado or not self.lista_ativa or self.ocupado:
            return
        pendentes = [item for item in self.registros_lista if item not in self.lista_finalizados]
        if not pendentes:
            self.pausar_lista("Lista concluída")
            self.status.configure(text="Lista concluída.", foreground=COR_SUCESSO_SUAVE)
            return
        try:
            detalhes = detalhes_espera(modo="lista")
            segundos = detalhes["total"]
        except ErroConsulta as erro:
            self.pausar_lista("Pausada: não foi possível ler o intervalo")
            self.status.configure(text=str(erro), foreground="#a13d29")
            return
        if segundos:
            motivo = " — pausa extra ativa" if detalhes["extra_ativa"] else " — intervalo normal"
            self.atualizar_progresso_lista(f"Próxima consulta em {segundos} segundos{motivo}")
            self.agendamento_lista = self.janela.after(1000, self.proximo_item_lista)
            return
        item = pendentes[0]
        self.lista.selection_set(item)
        self.lista.see(item)
        self.consultar(automatico=True, item_automatico=item)

    def alternar_token(self):
        self.token.configure(show="" if self.mostrar_token.get() else "*")

    def salvar(self):
        if self.ocupado or getattr(self, "lista_ativa", False):
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
                segundos = segundos_ate_liberar(modo="lista" if self.modo_lista() else "manual")
            except ErroConsulta as erro:
                self.botao.configure(state="disabled", text="Consultar selecionado" if self.modo_lista() else "Consultar")
                self.status.configure(text=str(erro), foreground="#a13d29")
            else:
                if segundos:
                    self.botao.configure(state="disabled", text=f"Consultar ({segundos} segundos)")
                else:
                    self.botao.configure(state="disabled" if getattr(self, "lista_ativa", False) else "normal",
                                          text="Lista em andamento" if getattr(self, "lista_ativa", False) else "Consultar selecionado" if self.modo_lista() else "Consultar")
        if hasattr(self, "temporizacao_lista"):
            try:
                detalhes = detalhes_espera(modo="lista")
                texto = resumo_temporizacao(detalhes) + " O ciclo continua no mesmo TXT pendente. Uma nova lista começa em zero."
                if detalhes["extra_ativa"]:
                    texto += f" Pausa extra ativa: {detalhes['total']} segundos de espera restante."
                self.temporizacao_lista.configure(text=texto)
            except ErroConsulta as erro:
                self.temporizacao_lista.configure(text=str(erro))
        if reagendar:
            self.janela.after(1000, self.atualizar_limite)

    def escrever(self, texto, sem_cadastro=False, inconclusivo=False):
        self.resultado.configure(state="normal", bg=FUNDO_SUCESSO_SUAVE if sem_cadastro else "#fff8e6" if inconclusivo else "white",
                                 fg=COR_SUCESSO_SUAVE if sem_cadastro else "#775d2b" if inconclusivo else "#183c35")
        self.resultado.delete("1.0", "end")
        self.resultado.insert("1.0", texto)
        self.resultado.configure(state="disabled")

    def consultar(self, automatico=False, item_automatico=None):
        if self.ocupado or getattr(self, "lista_ativa", False) and not automatico:
            return
        if getattr(self, "pendencia_resultado", None) is not None:
            try:
                self.concluir_resultado_pendente()
            except (ErroConsulta, ErroImportacaoLista) as erro:
                self.pausar_lista("Pausada: conclusão local pendente")
                self.status.configure(text=str(erro), foreground="#a13d29")
            else:
                self.atualizar_progresso_lista("Conclusão local recuperada; nenhuma nova consulta enviada")
                self.status.configure(text="Resultado pendente concluído localmente, sem repetir a consulta.", foreground=COR_SUCESSO_SUAVE)
            return
        modo_envio = "lista" if automatico or self.modo_lista() else "manual"
        try:
            self.resolver_pausa_pendente(modo_envio)
        except ErroConsulta as erro:
            if automatico:
                self.pausar_lista("Pausada: atualização da pausa extra pendente")
            self.status.configure(text=str(erro), foreground="#a13d29")
            return
        item_lista = None
        validado = False
        try:
            token = validar_token(self.token_lista if automatico else self.token.get())
            if automatico:
                item_lista = item_automatico
                tipo = self.tipo_lista_capturado
                chave = normalizar_chave(tipo, self.registros_lista[item_lista].numero)
            elif self.modo_lista():
                if self.importando:
                    raise ErroConsulta("Aguarde a importação do arquivo terminar antes de consultar uma linha.")
                selecionados = self.lista.selection()
                if not selecionados or selecionados[0] not in self.registros_lista:
                    raise ErroConsulta("Selecione uma linha da lista para consultar.")
                item_lista = selecionados[0]
                tipo = TIPOS.get(self.tipo_lista.get())
                chave = normalizar_chave(tipo, self.registros_lista[item_lista].numero)
            else:
                tipo = TIPOS.get(self.tipo.get())
                chave = normalizar_chave(tipo, self.chave.get())
            validado = True
            if item_lista:
                self.preparar_saida_lista()
            marcador_pausa = registrar_consulta(modo=modo_envio)
        except LimiteConsultas as erro:
            self.status.configure(text=str(erro), foreground="#775d2b")
            self.atualizar_limite(reagendar=False)
            if automatico:
                self.agendar_proximo_item()
            return
        except ErroConsulta as erro:
            self.status.configure(text=str(erro), foreground="#a13d29")
            self.escrever("Consulta não enviada. Confira os campos acima.")
            self.atualizar_limite(reagendar=False)
            if automatico:
                if validado:
                    self.pausar_lista("Pausada: confira o arquivo ou o intervalo")
                else:
                    self.lista.set(item_lista, "resultado", "Formato inválido")
                    self.pendencia_resultado = {"item": item_lista, "tipo": self.tipo_lista_capturado,
                                               "status": "Formato inválido", "texto": str(erro),
                                               "resultado": "entrada_invalida", "saida_gravada": False}
                    try:
                        self.concluir_resultado_pendente()
                    except (ErroConsulta, ErroImportacaoLista) as falha_saida:
                        self.pausar_lista("Pausada: não foi possível salvar o resultado")
                        self.status.configure(text=str(falha_saida), foreground="#a13d29")
                        return
                    self.atualizar_progresso_lista("Linha ignorada: formato inválido")
                    self.agendar_proximo_item()
            return
        self.ocupado = True
        self.item_em_consulta = item_lista
        self.tipo_em_consulta = tipo
        self.consulta_automatica_em_curso = automatico
        self.marcador_pausa_em_consulta = marcador_pausa
        if item_lista:
            self.lista.set(item_lista, "resultado", "Consultando…")
        if hasattr(self, "botao_abrir_lista"):
            self.botao_abrir_lista.configure(state="disabled")
            self.tipo_lista.configure(state="disabled")
        self.botao.configure(state="disabled", text="Consultando…")
        self.tipo.configure(state="disabled")
        self.chave.configure(state="disabled")
        self.token.configure(state="disabled")
        self.botao_salvar.configure(state="disabled")
        self.progresso.grid()
        self.progresso.start(12)
        self.status.configure(text="Consultando…", foreground="#526d66")
        self.escrever(f"Consultando {tipo}: {chave}")
        if hasattr(self, "botao_lista"):
            self.atualizar_controles_lista()
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
            falha_pausa = False
            avisos_finais = []
            marcador = self.marcador_pausa_em_consulta
            self.marcador_pausa_em_consulta = None
            if marcador is not None:
                marcador = dict(marcador, resposta_em=time.time())
                self.pendencias_pausa[marcador["modo"]] = marcador
                try:
                    self.resolver_pausa_pendente(marcador["modo"])
                except ErroConsulta as erro:
                    falha_pausa = True
                    avisos_finais.append(str(erro))
            self.botao.configure(state="normal", text="Consultar")
            self.tipo.configure(state="readonly")
            self.chave.configure(state="normal")
            self.token.configure(state="normal")
            self.botao_salvar.configure(state="normal")
            if hasattr(self, "botao_abrir_lista"):
                self.botao_abrir_lista.configure(state="disabled" if self.importando else "normal")
                self.tipo_lista.configure(state="readonly")
            self.progresso.stop()
            self.progresso.grid_remove()
            sem_cadastro = resultado == "sem_cadastro"
            inconclusivo = resultado == "inconclusivo"
            self.escrever(texto, sem_cadastro=sem_cadastro, inconclusivo=inconclusivo)
            self.status.configure(text=texto if sem_cadastro else "Consulta inconclusiva. Veja os detalhes abaixo." if inconclusivo else "Consulta concluída." if resultado == "sucesso" else "Consulta não concluída. Veja o motivo abaixo.",
                                  foreground=COR_SUCESSO_SUAVE if sem_cadastro else "#775d2b" if inconclusivo else "#116b55" if resultado == "sucesso" else "#a13d29")
            item_lista = getattr(self, "item_em_consulta", None)
            falha_local = False
            if item_lista and item_lista in self.registros_lista:
                rotulo = {"sucesso": "Dados recebidos", "sem_cadastro": "Sem Pix cadastrado", "inconclusivo": "Inconclusivo", "erro": "Erro na consulta"}.get(resultado, "Consulta concluída")
                self.lista.set(item_lista, "resultado", rotulo)
                self.pendencia_resultado = {"item": item_lista, "tipo": self.tipo_em_consulta,
                                           "status": rotulo, "texto": texto,
                                           "resultado": resultado, "saida_gravada": False}
                try:
                    self.concluir_resultado_pendente()
                except (ErroConsulta, ErroImportacaoLista) as erro:
                    falha_local = True
                    avisos_finais.append(str(erro))
                    self.lista.set(item_lista, "resultado", "Confira gravação/origem")
                    self.pausar_lista("Pausada: confira o arquivo de resultados e o TXT original")
                    self.status.configure(text=str(erro), foreground="#a13d29")
                    self.escrever(texto + "\n\n" + str(erro))
            self.item_em_consulta = None
            automatico = getattr(self, "consulta_automatica_em_curso", False)
            self.consulta_automatica_em_curso = False
            if falha_pausa:
                self.pausar_lista("Pausada: não foi possível atualizar a pausa extra")
                self.status.configure(text="Resultado recebido; atualização da pausa extra pendente. Confira os detalhes abaixo.", foreground="#a13d29")
                self.escrever(texto + "\n\n" + "\n\n".join(avisos_finais))
            if automatico and resultado not in ("sucesso", "sem_cadastro") and not falha_local and not falha_pausa:
                self.pausar_lista("Pausada após erro. Confira o resultado antes de retomar.")
            if hasattr(self, "botao_lista"):
                self.atualizar_controles_lista()
                self.atualizar_progresso_lista("Em andamento" if self.lista_ativa else "Pausada" if automatico else "")
            if automatico and self.lista_ativa:
                self.agendar_proximo_item()
            self.atualizar_limite(reagendar=False)
            self.chave.focus_set()
        self.janela.after(100, self.receber_resultado)

    def fechar(self):
        self.fechado = True
        self.lista_ativa = False
        if self.agendamento_lista is not None:
            self.janela.after_cancel(self.agendamento_lista)
            self.agendamento_lista = None
        self.token_lista = ""
        self.token.configure(state="normal")
        self.token.delete(0, "end")
        self.janela.destroy()


if __name__ == "__main__":
    Aplicativo(tk.Tk()).janela.mainloop()
