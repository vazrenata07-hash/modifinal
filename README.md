# Consultar Pix

Programa simples para consultar **uma chave Pix por vez**, com versões para
computador e Android. A consulta usa a API do Asaas, sem servidor próprio.

## Manual e lista

O modo **Manual** continua disponível. No PC, na aba **Lista**, use **Abrir TXT** para
selecionar um arquivo TXT. O app procura um
conjunto de 11 dígitos em cada linha, inclusive quando estiver acompanhado de
nomes, separadores ou pontuação usual de CPF/telefone.

Escolha CPF ou Telefone e clique em **Iniciar lista**. O PC consulta as linhas em
ordem automaticamente, uma por vez, respeitando **61 segundos entre envios** e o
intervalo de uma consulta manual anterior. O botão **Pausar** interrompe os próximos
envios; uma consulta já enviada termina normalmente. Ao continuar, as linhas já
processadas não são repetidas. A lista mostra o progresso e o resultado de cada linha.

Erros de limite, acesso, token, conexão ou respostas inconclusivas pausam a lista
para revisão, sem novas tentativas automáticas. Fechar o programa interrompe a
lista; reabrir preserva o contador, mas não inicia consultas automaticamente.

Ao iniciar a lista, o PC cria `resultados_pix_*.txt` na pasta do programa. A cada
resposta, acrescenta horário, linha original, tipo, chave, status e resposta
completa. O resultado parcial fica salvo ao pausar ou fechar. Retomar a mesma
lista continua no mesmo arquivo; importar outra lista cria uma nova saída ao
iniciar. O caminho aparece na interface. O token não é incluído na saída.
Essa associação fica no `cache.ini`: ao fechar, reabrir e importar novamente o
mesmo TXT pendente, **Iniciar lista** continua acrescentando ao arquivo de saída
anterior, sem apagar seu conteúdo. A execução só continua após esse clique.

Depois de salvar um resultado concluído, incluindo chave sem cadastro, o PC
remove a respectiva linha do **TXT original**. Linhas ignoradas e consultas com
erro ou resultado inconclusivo permanecem no arquivo. Antes da primeira remoção,
é criada uma cópia de segurança `.bak` ao lado do TXT. A atualização preserva a
codificação e as demais linhas. Se o arquivo for alterado por outro programa,
a lista pausa para ser importada novamente, sem sobrescrever a edição externa.

Importar ou selecionar não realiza consultas. Linhas sem candidato
ou com mais de um candidato diferente são ignoradas no resumo da importação.
Reconhecer 11 dígitos não confirma CPF válido nem cadastro Pix. Escolha o tipo
correto, como CPF ou Telefone.

A importação é local. O `cache.ini` guarda os caminhos para continuar a saída;
o conteúdo da lista não é copiado para o INI.

## Android 9 ou superior

Baixe [ConsultaPix-Android.apk](ConsultaPix-Android.apk) pelo botão
**Download raw file**, instale e abra **Consultar Pix**. Se o Android solicitar,
permita a instalação pelo navegador ou gerenciador de arquivos usado para baixar.
Cole o token, toque em **Salvar**, escolha o tipo da chave e toque em **Consultar**.
O APK atende Android 9 ou superior e não depende de serviços do Google.
A lista no Android continua com seleção e consulta individual por toque; a
execução automática está disponível apenas na versão para PC.

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
- O token pode ser salvo pelo botão **Salvar**. A lista automática do PC grava os
  resultados em TXT; consultas manuais e resultados do Android não são gravados.
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
- Não realiza transferências. No PC, a lista avança automaticamente somente depois
  de clicar em **Iniciar lista**; não repete tentativas que falharam automaticamente.
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
