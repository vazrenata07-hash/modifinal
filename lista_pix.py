"""Importação local de números com 11 dígitos; não consulta serviços externos."""

import re
from dataclasses import dataclass
from pathlib import Path


MAX_ARQUIVO = 50 * 1024 * 1024
PADROES_NUMERO = (
    re.compile(r"(?<![0-9])[0-9]{11}(?![0-9])"),
    re.compile(r"(?<![0-9])[0-9]{3}[.\s][0-9]{3}[.\s][0-9]{3}[-\s][0-9]{2}(?![0-9])"),
    re.compile(r"(?<![0-9])\(?[0-9]{2}\)?[\s.-]*[0-9]{5}[\s.-]*[0-9]{4}(?![0-9])"),
)


class ErroImportacaoLista(Exception):
    pass


@dataclass(frozen=True)
class RegistroLista:
    linha: int
    numero: str


@dataclass(frozen=True)
class ListaImportada:
    registros: tuple
    ambiguas: int
    sem_numero: int


def extrair_linhas(texto):
    registros = []
    ambiguas = 0
    sem_numero = 0
    for numero_linha, linha in enumerate(texto.splitlines(), start=1):
        if not linha.strip():
            continue
        candidatos = set()
        for padrao in PADROES_NUMERO:
            for encontrado in padrao.finditer(linha):
                numero = re.sub(r"[^0-9]", "", encontrado.group())
                if len(numero) == 11:
                    candidatos.add(numero)
        if len(candidatos) == 1:
            registros.append(RegistroLista(numero_linha, candidatos.pop()))
        elif len(candidatos) > 1:
            ambiguas += 1
        else:
            sem_numero += 1
    return ListaImportada(tuple(registros), ambiguas, sem_numero)


def decodificar_texto(conteudo):
    if conteudo.startswith((b"\xff\xfe", b"\xfe\xff")):
        return conteudo.decode("utf-16")
    if b"\x00" in conteudo:
        zeros_pares = conteudo[::2].count(b"\x00")
        zeros_impares = conteudo[1::2].count(b"\x00")
        return conteudo.decode("utf-16-le" if zeros_impares >= zeros_pares else "utf-16-be")
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("cp1252")


def importar_lista(caminho):
    caminho = Path(caminho)
    if caminho.suffix.lower() != ".txt":
        raise ErroImportacaoLista("Escolha um arquivo TXT.")
    try:
        if caminho.stat().st_size > MAX_ARQUIVO:
            raise ErroImportacaoLista("Escolha um arquivo de até 50 MB.")
        texto = decodificar_texto(caminho.read_bytes())
    except ErroImportacaoLista:
        raise
    except (OSError, UnicodeError):
        raise ErroImportacaoLista("Não foi possível abrir esse arquivo. Confira o formato e a permissão de leitura.") from None
    resultado = extrair_linhas(texto)
    if not resultado.registros:
        detalhe = " Há linhas com mais de um número diferente; elas foram ignoradas." if resultado.ambiguas else ""
        raise ErroImportacaoLista("Nenhuma linha com um único conjunto de 11 dígitos foi identificada." + detalhe)
    return resultado
