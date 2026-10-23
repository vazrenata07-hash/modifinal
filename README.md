# Consultar Pix

Programa simples para consultar **uma chave Pix por vez**, com versões para
computador e Android. A consulta usa a API do Asaas, sem servidor próprio.

## Manual e lista

O modo **Manual** continua disponível. Na aba **Lista**, use **Abrir lista** para
selecionar um arquivo TXT. O app procura um
conjunto de 11 dígitos em cada linha, inclusive quando estiver acompanhado de
nomes, separadores ou pontuação usual de CPF/telefone.

Selecione uma linha identificada e clique em **Consultar** para enviar somente
aquele número. Importar ou selecionar não realiza consultas. Linhas sem candidato
ou com mais de um candidato diferente são ignoradas no resumo da importação.
Reconhecer 11 dígitos não confirma CPF válido nem cadastro Pix. Escolha o tipo
correto, como CPF ou Telefone.

Os arquivos são lidos localmente e a lista não é salva
automaticamente pelo programa.

## Android 9 ou superior

Baixe [ConsultaPix-Android.apk](ConsultaPix-Android.apk) pelo botão
**Download raw file**, instale e abra **Consultar Pix**. Se o Android solicitar,
permita a instalação pelo navegador ou gerenciador de arquivos usado para baixar.
Cole o token, toque em **Salvar**, escolha o tipo da chave e toque em **Consultar**.
O APK atende Android 9 ou superior e não depende de serviços do Google.

## Usar no Windows

1. Baixe [ConsultaPix.zip](ConsultaPix.zip) e clique em **Download raw file** no GitHub.
2. Extraia o ZIP para uma pasta.
3. Abra **Iniciar.bat** com dois cliques.
4. Cole seu **token de produção**, escolha o tipo da chave e clique em **Consultar**.
5. Para não precisar colar novamente, clique em **Salvar** ao lado do token.

O botão **Salvar** grava `cache.ini` na mesma pasta de `consulta_pix.py`
(ou do executável, se o programa for empacotado). O token salvo é carregado
automaticamente na próxima abertura. No Android, o arquivo fica na pasta
privada do aplicativo e o token é criptografado com o Android Keystore.
O salvamento só acontece ao clicar ou tocar em **Salvar**.
No PC, o INI contém o token em texto: mantenha esse arquivo privado e não o envie
ao GitHub nem junto do programa. O arquivo está excluído pelo `.gitignore`.

É necessário ter **Python 3.9 ou superior com Tkinter**. Se ainda não tiver,
instale pelo [site oficial](https://www.python.org/downloads/), marque
**Add Python to PATH** e mantenha o componente Tcl/Tk selecionado.
O programa usa apenas os componentes padrão do Python.

## Gerar um EXE no Windows

1. Baixe e extraia o [ConsultaPix.zip](ConsultaPix.zip) atualizado.
2. Com Python 3.9 ou superior instalado, abra **Gerar_EXE.bat** com dois cliques.
3. Aguarde: o gerador prepara um ambiente separado e instala o PyInstaller automaticamente.
4. Abra **ConsultarPix.exe**, criado na mesma pasta.

A primeira geração precisa de internet para baixar o PyInstaller. O computador
que usar o EXE pronto não precisa ter Python instalado; a consulta Pix continua
precisando de internet. O gerador roda no Windows e o EXE acompanha a arquitetura
do Python usado para gerá-lo.

O `cache.ini` permanece separado, na pasta do EXE, preservando o token salvo e
o contador existente. O gerador não embute esse arquivo no executável. Feche
`ConsultarPix.exe` antes de gerar uma nova versão. Os arquivos auxiliares da
geração ficam em `.gerador-exe/`.

## Conseguir o token

Na sua conta Asaas aprovada, abra **Menu do usuário → Integrações → Chaves API**.
O token da API é diferente da chave Pix que você quer consultar.
Use um token de **produção**; este programa não usa o ambiente de testes.

[Instruções oficiais para gerar a chave de API](https://central.ajuda.asaas.com/hc/pt-br/articles/33618186066331-Como-gerar-uma-nova-chave-de-API-no-Asaas).

## Mac e Linux

Com Python e Tkinter instalados, execute o iniciador na pasta do programa:

```sh
sh Iniciar.command
```

No Mac também há o iniciador `Iniciar.command`. No Ubuntu/Debian, se faltar Tkinter:

```sh
sudo apt install python3 python3-tk
```

## Funcionamento

- Aceita CPF, CNPJ numérico ou alfanumérico, e-mail, telefone brasileiro e chave aleatória.
- CPF e telefone podem ter 11 dígitos: selecione o tipo correto.
- Consulta diretamente `GET https://api.asaas.com/v3/pix/addressKeys/external`.
- Exibe os dados recebidos do Asaas, incluindo titular e instituição quando disponíveis.
- O token pode ser salvo pelo botão **Salvar**. Consultas e resultados não são gravados.
- Chave não cadastrada e HTTP 404 sem detalhes deste fluxo aparecem em verde suave:
  **Sucesso, CPF sem Pix cadastrado.** O texto acompanha o tipo selecionado.
- Mensagens de limite, tentativas excedidas, acesso negado e outros erros continuam separadas.
- Os modos Manual e Lista compartilham uma consulta a cada 61 segundos
  (1 minuto e 1 segundo).
  Depois de cada envio, mostra uma contagem regressiva até liberar uma nova consulta.
  Os horários são salvos localmente e continuam valendo ao fechar e reabrir o app.
- Consultas enviadas contam mesmo quando retornam erro. Erros de preenchimento
  detectados antes do envio não consomem essa contagem local.
- Salvar os horários não salva o token: para guardar o token, use **Salvar**.
- Não realiza transferências, consultas automáticas ou novas tentativas sozinho.
- Erros de rede, token e permissão não são tratados como prova de chave inexistente.

O Asaas documenta até **5 consultas por minuto**, além de uma cota de fichas.
O acesso depende da aprovação e das permissões da conta. As condições e eventuais
tarifas da API são definidas pelo Asaas; a gratuidade específica por consulta
não foi confirmada. [Documentação oficial](https://docs.asaas.com/docs/consultar-chave-pix).

## Validação

Os testes usam respostas simuladas de sucesso, falhas HTTP, rede e formato de entrada.
Não foi feita consulta real com um token de produção.
O gerador de EXE é entregue para execução no seu Windows; não foi executado neste ambiente.

```sh
python3 -m unittest discover -s tests -v
```
