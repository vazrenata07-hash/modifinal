#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! python3 -c 'import sys, tkinter; assert sys.version_info >= (3,9)' 2>/dev/null; then
    printf '\nInstale Python 3.9 ou mais recente com Tkinter: https://www.python.org/downloads/\n'
    printf 'No Ubuntu/Debian: sudo apt install python3 python3-tk\n'
    printf 'Pressione Enter para fechar.\n'
    read -r consulta_pix_resposta
    exit 1
fi
python3 "$PWD/consulta_pix.py"
consulta_pix_status=$?
if [ "$consulta_pix_status" -ne 0 ]; then
    printf '\nNao foi possivel abrir. Confira a mensagem acima. Pressione Enter.\n'
    read -r consulta_pix_resposta
fi
exit "$consulta_pix_status"
