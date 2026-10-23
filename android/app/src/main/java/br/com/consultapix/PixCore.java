package br.com.consultapix;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Input and response rules independent of Android so they can be tested on the JVM. */
public final class PixCore {
    private PixCore() {}
    public static final String[] TYPES = {"CPF", "CNPJ", "EMAIL", "PHONE", "EVP"};
    public static final String[] TYPE_LABELS = {"CPF", "CNPJ", "E-mail", "Telefone", "Aleatória"};
    public static final int MAX_RESPONSE = 262144;
    public static final long WINDOW_MS = 61000L;

    public static List<Long> recentQueries(List<Long> history, long now) {
        List<Long> recent = new ArrayList<>();
        if (history != null) for (Long time : history) {
            if (time != null && time > now - WINDOW_MS) recent.add(time);
        }
        java.util.Collections.sort(recent);
        return recent;
    }

    public static long waitMillis(List<Long> history, long now) {
        List<Long> recent = recentQueries(history, now);
        if (recent.isEmpty()) return 0L;
        return Math.max(0L, recent.get(recent.size() - 1) + WINDOW_MS - now);
    }

    public static String countdown(long millis) {
        long seconds = (millis + 999L) / 1000L;
        return String.format(Locale.ROOT, "%02d:%02d", seconds / 60L, seconds % 60L);
    }

    public static final class InputError extends Exception {
        public InputError(String message) { super(message); }
    }

    public static String normalizeToken(String value) throws InputError {
        String token = value == null ? "" : value.trim();
        if (token.isEmpty()) throw new InputError("Cole seu token de produção.");
        if (token.length() > 4096 || !token.matches("[!-~]+"))
            throw new InputError("O token contém espaços ou caracteres inválidos. Copie-o novamente.");
        if (token.startsWith("$aact_hmlg_"))
            throw new InputError("Esse token é de testes. Use um token de produção para consultar chaves reais.");
        return token;
    }

    public static String normalizeKey(String type, String value) throws InputError {
        String key = value == null ? "" : value.trim();
        if (key.isEmpty() || key.length() > 200 || key.matches("(?s).*[\\x00-\\x1f].*"))
            throw new InputError("Digite uma única chave Pix, sem quebras de linha.");
        if ("CPF".equals(type) || "PHONE".equals(type)) {
            if (!key.matches("[0-9\\s.()/+\\-]+"))
                throw new InputError("Use somente números e a pontuação da chave.");
            key = key.replaceAll("[^0-9]", "");
            if ("PHONE".equals(type) && key.length() == 13 && key.startsWith("55")) key = key.substring(2);
            if (key.length() != 11) throw new InputError("PHONE".equals(type)
                    ? "Telefone: informe DDD + número, com 11 dígitos."
                    : "CPF: informe 11 dígitos.");
            return key;
        }
        if ("CNPJ".equals(type)) {
            if (!key.matches("[A-Za-z0-9\\s./\\-]+")) throw new InputError("Confira o CNPJ informado.");
            key = key.replaceAll("[\\s./\\-]", "").toUpperCase(Locale.ROOT);
            if (!key.matches("[A-Z0-9]{12}[0-9]{2}"))
                throw new InputError("CNPJ: informe 14 caracteres, com os dois últimos numéricos.");
            return key;
        }
        if ("EMAIL".equals(type)) {
            if (key.length() > 77 || !key.matches("[^\\s@]+@[^\\s@]+\\.[^\\s@]+"))
                throw new InputError("Confira o e-mail informado.");
            return key.toLowerCase(Locale.ROOT);
        }
        if ("EVP".equals(type)) {
            if (!key.matches("[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"))
                throw new InputError("Confira a chave aleatória, incluindo os hífens.");
            return key.toLowerCase(Locale.ROOT);
        }
        throw new InputError("Selecione o tipo da chave Pix.");
    }

    public static final class ApiError {
        public final String code;
        public final String description;
        public ApiError(String code, String description) {
            this.code = code == null ? "" : code;
            this.description = description == null ? "" : description;
        }
    }

    public static boolean isExplicitMissing(int http, List<ApiError> errors) {
        if (http != 400 && http != 404) return false;
        if (errors == null || errors.isEmpty()) return http == 404;
        for (ApiError error : errors) {
            String text = fold(error.code + " " + error.description);
            if (text.matches("(?s).*(limite|excedid|excedeu|tentativas|muitas consultas|many requests|rate.limit|token|fichas|bloquead|restric|unauthorized|forbidden|permiss|autoriz|acesso|indispon|unavail|erro do servidor|erro interno|nao foi possivel|fraud|excess|cota|quota|esgot|denied|nao permit|segur).*"))
                return false;
        }
        for (ApiError error : errors) {
            String text = fold(error.description);
            if (text.matches("(?s).*\\bchave (?:pix )?(?:informada )?nao (?:foi )?(?:encontrada|cadastrada|registrada)\\b.*")
                    || text.contains("pix key not found")
                    || text.contains("cpf sem pix cadastrado")
                    || text.contains("cpf nao cadastrado como chave pix")
                    || text.contains("cpf nao possui chave pix")
                    || text.matches("(?s).*nao (?:foi )?encontrad[ao].{0,30}chave pix.*")
                    || text.contains("chave pix nao esta cadastrada")
                    || text.contains("chave informada nao esta cadastrada")) return true;
        }
        return false;
    }

    private static String fold(String value) {
        return Normalizer.normalize(value, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").toLowerCase(Locale.ROOT).trim();
    }

    public static String missingMessage(String type) {
        if ("CPF".equals(type)) return "Sucesso, CPF sem Pix cadastrado.";
        if ("CNPJ".equals(type)) return "Sucesso, CNPJ sem Pix cadastrado.";
        if ("EMAIL".equals(type)) return "Sucesso, e-mail sem Pix cadastrado.";
        if ("PHONE".equals(type)) return "Sucesso, telefone sem Pix cadastrado.";
        return "Sucesso, chave Pix não cadastrada.";
    }

    public static String errorMessage(int http, List<ApiError> errors) {
        String message;
        if (http == 401) message = "Token não autorizado. Confira se ele é de produção e está válido.";
        else if (http == 403) message = "Acesso negado. Confira a aprovação da conta e as permissões da API.";
        else if (http == 429) message = "Limite de consultas ou cota atingido. Aguarde antes de tentar novamente.";
        else if (http == 404) message = "O serviço retornou HTTP 404 sem confirmar a situação da chave. Não foi possível confirmar se há Pix cadastrado.";
        else if (http >= 500) message = "O serviço está indisponível no momento. Tente novamente mais tarde.";
        else message = "Não foi possível concluir a consulta. Confira os detalhes abaixo.";
        StringBuilder result = new StringBuilder(message).append("\n\nHTTP ").append(http);
        if (errors != null) {
            for (int i = 0; i < Math.min(errors.size(), 3); i++) {
                ApiError error = errors.get(i);
                if (!error.code.isEmpty()) result.append("\nCódigo: ").append(error.code);
                if (!error.description.isEmpty()) result.append("\n").append(error.description);
            }
        }
        return result.toString();
    }

    public static String sanitize(String value, String token) {
        String clean = value.replaceAll("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]", "");
        return token == null || token.isEmpty() ? clean : clean.replace(token, "[token oculto]");
    }
}
