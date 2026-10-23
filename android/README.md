# Consultar Pix para Android

Aplicativo nativo para **Android 9 ou superior** (API mínima 28), sem servidor,
sem navegador e sem bibliotecas externas em tempo de execução.

## Usar

1. Instale `ConsultaPix-Android.apk` no aparelho. O Android pode pedir que você permita
   a instalação pelo aplicativo usado para abrir o APK.
2. Cole o token de produção. Se quiser lembrá-lo neste aparelho, toque em **Salvar**.
3. Selecione o tipo da chave, informe uma única chave Pix e toque em **Consultar**.

### Lista local de TXT

Toque em **Lista → Importar TXT** e escolha o arquivo no seletor do
Android. A importação ocorre localmente e identifica um número de **11 dígitos por
linha**, contíguo, como CPF pontuado ou telefone com DDD. Ela não verifica checksum
nem confirma se o CPF existe. Linhas com mais de um candidato são ignoradas como
ambíguas; sequências maiores, como CNPJ de 14 dígitos, não são recortadas.

Depois toque em **Selecionar linha**, escolha a linha, confira **CPF ou Telefone**
no campo Tipo e toque em **Consultar**. Só a linha selecionada é consultada por
esse clique. Não há consulta automática, varredura ou envio em lote. Importar ou
selecionar linhas não usa a API e não consome o intervalo local. O modo **Manual**
continua disponível. A lista e os resultados ficam apenas na memória do aplicativo.

TXT aceita UTF-8, UTF-8 com BOM, UTF-16 e Windows-1252/Latin-1. Limites de
importação: texto de até 8 MB e até 10.000 linhas identificadas. Nenhum arquivo
é enviado para o serviço. Os demais formatos não são importados.

O arquivo `cache.ini` fica na pasta privada de dados do aplicativo. O token salvo é
criptografado com AES-GCM e uma chave do Android Keystore. O botão **Salvar** é a
única ação que grava ou substitui o token. Para esquecer o token, esvazie o campo e
toque em **Salvar**. Isso preserva o contador de consultas.

Os modos Manual e Lista compartilham **uma consulta a cada 61 segundos**. Cada envio
bloqueia o botão por **61 segundos**, com contagem regressiva `MM:SS`. O histórico fica
no mesmo arquivo INI e continua valendo depois de fechar/reabrir o aplicativo ou
reiniciar o aparelho. Tentativas enviadas que retornam erro também contam; erros
locais de preenchimento não contam. Esse limite local não garante ausência de
restrições adicionais impostas pelo serviço.

Uma resposta que confirme explicitamente a ausência da chave ou HTTP 404 sem
detalhes mostra a mensagem verde suave “Sucesso, CPF sem Pix cadastrado.” (ou o
tipo correspondente). CPF inválido, limite excedido, erro de token, falhas de
acesso e HTTP 404 com descrição de endpoint inexistente continuam separados.

## Compilar

O APK usa API 35 como alvo e Build Tools 35.0.0. O script abaixo funciona com Java
21 e o compilador Eclipse ECJ 3.42.0. Também são necessários Python 3 e Bash.
As ferramentas e a chave privada de assinatura não fazem parte do código-fonte.

Defina estas variáveis no seu ambiente:

```sh
export ANDROID_JAR=/caminho/sdk/platforms/android-35/android.jar
export ANDROID_BUILD_TOOLS=/caminho/sdk/build-tools/35.0.0
export ECJ_JAR=/caminho/ecj-3.42.0.jar
export PIX_KEYSTORE=/caminho/seguro/consultapix.p12
export PIX_KEY_ALIAS=consultapix
read -r -s -p 'Senha da chave de assinatura: ' PIX_KEYSTORE_PASSWORD
export PIX_KEYSTORE_PASSWORD
bash scripts/build.sh
```

Para criar sua própria chave de assinatura antes da primeira compilação:

```sh
keytool -genkeypair -keystore "$PIX_KEYSTORE" -storetype PKCS12 \
  -alias "$PIX_KEY_ALIAS" -keyalg RSA -keysize 3072 -validity 10000 \
  -storepass:env PIX_KEYSTORE_PASSWORD -keypass:env PIX_KEYSTORE_PASSWORD \
  -dname 'CN=Consultar Pix, OU=Aplicativo local, O=Consultar Pix, C=BR'
```

A saída é `build/ConsultaPix-Android.apk`. O script compila, gera DEX,
alinha e assina o APK.

## Validação e limites

- Os testes JVM cobrem entradas, distinção entre ausência/erros, janela móvel e
  manutenção do intervalo depois de recarregar o histórico.
- O manifesto declara API mínima 28 e o APK é alinhado e assinado pelas ferramentas Android.
- Não foi realizado teste em aparelho físico/emulador nem consulta real com token.
- A única permissão de manifesto é internet. A lista usa o seletor de arquivos do
  Android para acessar só o documento escolhido, sem permissão geral de armazenamento.
- Apenas consultas GET são implementadas; o aplicativo não realiza transferências.
