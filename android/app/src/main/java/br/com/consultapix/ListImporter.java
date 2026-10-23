package br.com.consultapix;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Finds exactly one eleven-digit candidate per physical text line; never makes requests. */
public final class ListImporter {
    private ListImporter() {}
    public static final int MAX_TEXT_BYTES = 8 * 1024 * 1024;
    public static final int MAX_TEXT_CHARS = 2 * 1024 * 1024;
    public static final int MAX_ITEMS = 10000;
    private static final Pattern CANDIDATE = Pattern.compile(
            "(?<![0-9])(?:[0-9]{3}\\.[0-9]{3}\\.[0-9]{3}-[0-9]{2}"
            + "|\\([0-9]{2}\\)[ \\t]*[0-9]{5}[- .]?[0-9]{4}"
            + "|[0-9]{2}[ \\t.-]+[0-9]{5}[- .]?[0-9]{4}"
            + "|[0-9]{11})(?![0-9])");

    public static final class Item {
        public final int line;
        public final String digits;
        public String state = "Não consultado";
        Item(int line, String digits) { this.line = line; this.digits = digits; }
        public String label() { return "Linha " + line + " · " + digits + "\n" + state; }
    }

    public static final class Result {
        public final List<Item> items = new ArrayList<>();
        public int ambiguousLines;
        public int ignoredLines;
        public int totalLines;
    }

    public static String decode(byte[] bytes) throws Exception {
        if (bytes.length > MAX_TEXT_BYTES) throw new Exception("O arquivo de texto é maior que 8 MB.");
        int start = 0;
        Charset charset = StandardCharsets.UTF_8;
        if (bytes.length >= 3 && (bytes[0] & 255) == 239 && (bytes[1] & 255) == 187 && (bytes[2] & 255) == 191) {
            start = 3;
        } else if (bytes.length >= 2 && (bytes[0] & 255) == 255 && (bytes[1] & 255) == 254) {
            start = 2;
            charset = StandardCharsets.UTF_16LE;
        } else if (bytes.length >= 2 && (bytes[0] & 255) == 254 && (bytes[1] & 255) == 255) {
            start = 2;
            charset = StandardCharsets.UTF_16BE;
        } else {
            int oddZeros = 0, evenZeros = 0;
            for (int i = 0; i < Math.min(bytes.length, 512); i++) {
                if (bytes[i] == 0) { if ((i & 1) == 0) evenZeros++; else oddZeros++; }
            }
            if (oddZeros > 8 && oddZeros > evenZeros * 3) charset = StandardCharsets.UTF_16LE;
            else if (evenZeros > 8 && evenZeros > oddZeros * 3) charset = StandardCharsets.UTF_16BE;
        }
        String text;
        try {
            text = charset.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(bytes, start, bytes.length - start)).toString();
        } catch (CharacterCodingException invalid) {
            if (!charset.equals(StandardCharsets.UTF_8)) throw new Exception("Não foi possível ler a codificação do arquivo.");
            text = new String(bytes, start, bytes.length - start, Charset.forName("windows-1252"));
        }
        if (text.length() > MAX_TEXT_CHARS) throw new Exception("O texto é muito grande. Divida o arquivo em partes menores.");
        return text;
    }

    public static Result parse(String text) throws Exception {
        if (text == null || text.length() > MAX_TEXT_CHARS) throw new Exception("O texto é muito grande.");
        Result result = new Result();
        String[] lines = text.replace('\u000c', '\n').split("\\r\\n|\\n|\\r", -1);
        result.totalLines = lines.length;
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            if (line.trim().isEmpty()) continue;
            Matcher matcher = CANDIDATE.matcher(line);
            String candidate = null;
            int count = 0;
            while (matcher.find()) {
                count++;
                if (count > 1) break;
                candidate = matcher.group().replaceAll("[^0-9]", "");
            }
            if (count == 1 && candidate != null && candidate.length() == 11) {
                if (result.items.size() >= MAX_ITEMS) throw new Exception("Há mais de 10.000 linhas identificadas. Divida o arquivo.");
                result.items.add(new Item(i + 1, candidate));
            } else if (count > 1) result.ambiguousLines++;
            else result.ignoredLines++;
        }
        return result;
    }
}
