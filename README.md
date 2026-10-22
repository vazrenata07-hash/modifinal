# Consultar Pix

Programa simples para consultar **uma chave Pix por vez** usando a API do Asaas.
Roda no seu computador, com interface gráfica e sem servidor.

## Usar no Windows

1. Baixe [ConsultaPix.zip](ConsultaPix.zip) e clique em **Download raw file** no GitHub.
2. Extraia o ZIP para uma pasta.
3. Abra **Iniciar.bat** com dois cliques.
4. Cole seu **token de produção do Asaas**, escolha o tipo da chave e clique em **Consultar**.

É necessário ter **Python 3.9 ou superior com Tkinter**. Se ainda não tiver,
instale pelo [site oficial](https://www.python.org/downloads/), marque
**Add Python to PATH** e mantenha o componente Tcl/Tk selecionado.
Não precisa instalar pacotes com `pip`.

## Conseguir o token

Na sua conta Asaas aprovada, abra **Menu do usuário → Integrações → Chaves API**.
O token da API é diferente da chave Pix que você quer consultar.
Use um token de **produção**; este programa não usa o ambiente de testes.

[Instruções oficiais para gerar a chave de API](https://central.ajuda.asaas.com/hc/pt-br/articles/33618186066331-Como-gerar-uma-nova-chave-de-API-no-Asaas).

## Mac e Linux

Com Python e Tkinter instalados, execute na pasta do programa:

```sh
python3 consulta_pix.py
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
- O token fica apenas na memória durante o uso. O programa não salva consultas ou resultados.
- Não realiza transferências, importação de listas, consultas automáticas ou novas tentativas sozinho.
- Erros de rede, token e permissão não são tratados como prova de chave inexistente.

O Asaas documenta até **5 consultas por minuto**, além de uma cota de fichas.
O acesso depende da aprovação e das permissões da conta. As condições e eventuais
tarifas da API são definidas pelo Asaas; a gratuidade específica por consulta
não foi confirmada. [Documentação oficial](https://docs.asaas.com/docs/consultar-chave-pix).

## Validação

Os testes usam respostas simuladas de sucesso, falhas HTTP, rede e formato de entrada.
Não foi feita consulta real com um token de produção.

```sh
python3 -m unittest discover -s tests -v
```
