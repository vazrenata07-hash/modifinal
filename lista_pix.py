"""Importação local de números com 11 dígitos; não consulta serviços externos."""

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
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
    origem: object = None


@dataclass
class OrigemLista:
    caminho: Path
    linhas: tuple
    encoding: str
    bom: bytes
    original: bytes
    esperado: bytes
    removidas: set = field(default_factory=set)
    backup: object = None


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
    return decodificar_com_formato(conteudo)[0]


def decodificar_com_formato(conteudo):
    if conteudo.startswith(b"\xff\xfe"):
        return conteudo[2:].decode("utf-16-le"), "utf-16-le", b"\xff\xfe"
    if conteudo.startswith(b"\xfe\xff"):
        return conteudo[2:].decode("utf-16-be"), "utf-16-be", b"\xfe\xff"
    if conteudo.startswith(b"\xef\xbb\xbf"):
        return conteudo[3:].decode("utf-8"), "utf-8", b"\xef\xbb\xbf"
    if b"\x00" in conteudo:
        zeros_pares = conteudo[::2].count(b"\x00")
        zeros_impares = conteudo[1::2].count(b"\x00")
        encoding = "utf-16-le" if zeros_impares >= zeros_pares else "utf-16-be"
        return conteudo.decode(encoding), encoding, b""
    try:
        return conteudo.decode("utf-8"), "utf-8", b""
    except UnicodeDecodeError:
        return conteudo.decode("cp1252"), "cp1252", b""


def verificar_origem(origem):
    try:
        if origem.caminho.read_bytes() != origem.esperado:
            raise ErroImportacaoLista("O TXT original foi alterado fora do programa. A lista foi pausada; importe o arquivo novamente para continuar.")
    except OSError:
        raise ErroImportacaoLista("Não foi possível acessar o TXT original. A lista foi pausada; confira o arquivo antes de continuar.") from None


def criar_backup_origem(origem):
    if origem.backup is not None:
        return
    nome = origem.caminho.name + "." + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".bak"
    destino = origem.caminho.with_name(nome)
    criado = False
    try:
        descritor = os.open(str(destino), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        criado = True
        with os.fdopen(descritor, "wb") as arquivo:
            arquivo.write(origem.original)
            arquivo.flush()
            os.fsync(arquivo.fileno())
    except OSError:
        if criado:
            try:
                destino.unlink()
            except OSError:
                pass
        raise ErroImportacaoLista("O resultado foi salvo, mas não foi possível criar o backup do TXT. O original não foi alterado.") from None
    origem.backup = destino


def remover_linha_consultada(origem, linha_original):
    if linha_original in origem.removidas:
        return
    verificar_origem(origem)
    if not 1 <= linha_original <= len(origem.linhas):
        raise ErroImportacaoLista("O resultado foi salvo, mas a linha original não foi localizada. Importe o TXT novamente.")
    criar_backup_origem(origem)
    removidas = origem.removidas | {linha_original}
    texto = "".join(linha for indice, linha in enumerate(origem.linhas, start=1) if indice not in removidas)
    novo_conteudo = origem.bom + texto.encode(origem.encoding)
    temporario = None
    try:
        modo = origem.caminho.stat().st_mode & 0o777
        with tempfile.NamedTemporaryFile(mode="wb", dir=origem.caminho.parent,
                                         prefix=".pix-origem-", suffix=".tmp", delete=False) as arquivo:
            temporario = Path(arquivo.name)
            if os.name != "nt":
                os.chmod(temporario, modo)
            arquivo.write(novo_conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        verificar_origem(origem)
        os.replace(temporario, origem.caminho)
    except ErroImportacaoLista:
        raise
    except (OSError, UnicodeError):
        raise ErroImportacaoLista("O resultado foi salvo, mas não foi possível remover a linha do TXT original. A lista foi pausada.") from None
    finally:
        if temporario is not None:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
    origem.removidas = removidas
    origem.esperado = novo_conteudo


def importar_lista(caminho):
    caminho = Path(caminho)
    if caminho.suffix.lower() != ".txt":
        raise ErroImportacaoLista("Escolha um arquivo TXT.")
    try:
        if caminho.stat().st_size > MAX_ARQUIVO:
            raise ErroImportacaoLista("Escolha um arquivo de até 50 MB.")
        conteudo = caminho.read_bytes()
        texto, encoding, bom = decodificar_com_formato(conteudo)
    except ErroImportacaoLista:
        raise
    except (OSError, UnicodeError):
        raise ErroImportacaoLista("Não foi possível abrir esse arquivo. Confira o formato e a permissão de leitura.") from None
    resultado = extrair_linhas(texto)
    if not resultado.registros:
        detalhe = " Há linhas com mais de um número diferente; elas foram ignoradas." if resultado.ambiguas else ""
        raise ErroImportacaoLista("Nenhuma linha com um único conjunto de 11 dígitos foi identificada." + detalhe)
    origem = OrigemLista(caminho.resolve(), tuple(texto.splitlines(keepends=True)), encoding, bom, conteudo, conteudo)
    return ListaImportada(resultado.registros, resultado.ambiguas, resultado.sem_numero, origem)
