package br.com.consultapix;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

public final class PixCoreTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    private static List<PixCore.ApiError> error(String description) {
        return Collections.singletonList(new PixCore.ApiError("", description));
    }
    public static void main(String[] args) throws Exception {
        check(PixCore.normalizeKey("CPF", "123.456.789-00").equals("12345678900"), "CPF");
        check(PixCore.normalizeKey("CNPJ", "99.999.a03/0001-06").equals("99999A03000106"), "CNPJ alfanumérico");
        check(PixCore.normalizeKey("PHONE", "+55 (47) 99651-5839").equals("47996515839"), "Telefone");
        check(PixCore.normalizeKey("EMAIL", " TESTE@example.com ").equals("teste@example.com"), "E-mail");
        check(PixCore.normalizeKey("EVP", "123E4567-E89B-12D3-A456-426655440000").equals("123e4567-e89b-12d3-a456-426655440000"), "EVP");
        for (String key : new String[]{"", "123", "abc12345678900", "12345678900\n98765432100"}) {
            boolean invalid = false;
            try { PixCore.normalizeKey("CPF", key); } catch (PixCore.InputError expected) { invalid = true; }
            check(invalid, "Entrada inválida: " + key);
        }
        for (String token : new String[]{"", "token\nquebrado", "$aact_hmlg_ficticio", "tökén"}) {
            boolean invalid = false;
            try { PixCore.normalizeToken(token); } catch (PixCore.InputError expected) { invalid = true; }
            check(invalid, "Token inválido");
        }
        check(PixCore.isExplicitMissing(400, error("Chave Pix não encontrada.")), "Ausência explícita 400");
        check(PixCore.isExplicitMissing(404, error("CPF não cadastrado como chave Pix.")), "Ausência explícita 404");
        check(!PixCore.isExplicitMissing(404, new ArrayList<>()), "404 vazio é inconclusivo");
        check(!PixCore.isExplicitMissing(404, error("Endpoint não encontrado.")), "Endpoint inexistente");
        check(!PixCore.isExplicitMissing(400, error("CPF inválido.")), "CPF inválido não confirma ausência");
        check(!PixCore.isExplicitMissing(400, Collections.singletonList(new PixCore.ApiError("pix_key_not_found", ""))), "Código inventado não basta");
        for (int http : new int[]{401, 403, 429, 500})
            check(!PixCore.isExplicitMissing(http, error("Chave Pix não encontrada.")), "HTTP impede sucesso: " + http);
        for (String other : new String[]{"Limite de consultas excedido.", "Acesso negado.", "Serviço indisponível.", "Não foi possível consultar a chave Pix."})
            check(!PixCore.isExplicitMissing(400, Arrays.asList(new PixCore.ApiError("", "Chave Pix não encontrada."), new PixCore.ApiError("", other))), "Erro combinado: " + other);
        check(PixCore.sanitize("Titular Asaas; token-ficticio", "token-ficticio").equals("Titular Asaas; [token oculto]"), "Preserva titular e oculta token");

        long now = 1700000000000L;
        List<Long> history = new ArrayList<>();
        check(PixCore.waitMillis(history, now) == 0, "Primeira consulta liberada");
        history.add(now);
        check(PixCore.waitMillis(history, now + 1000) == 0, "Segunda consulta liberada");
        history.add(now + 1000);
        check(PixCore.waitMillis(history, now + 2000) == 118000L, "Terceira bloqueada");
        check(PixCore.countdown(118000L).equals("01:58"), "Contagem regressiva");
        check(PixCore.countdown(1L).equals("00:01"), "Arredonda segundos para cima");
        List<Long> reloaded = new ArrayList<>(history);
        check(PixCore.waitMillis(reloaded, now + 30000) == 90000L, "Reabertura não zera histórico");
        check(PixCore.waitMillis(history, now + 120000) == 0, "Limite exato da janela libera");
        List<Long> recent = PixCore.recentQueries(history, now + 120000);
        recent.add(now + 120000);
        check(PixCore.waitMillis(recent, now + 120000) == 1000L, "Janela móvel impede terceira ainda presente");
        check(PixCore.waitMillis(recent, now + 121000) == 0, "Próxima expiração libera");
        check(PixCore.recentQueries(history, now + 240000).isEmpty(), "Histórico antigo expira");
        check(PixCore.waitMillis(history, now - 1000) > 0, "Relógio regressivo não libera imediatamente");
        System.out.println("PixCoreTest: " + checks + " verificações passaram.");
    }
}
