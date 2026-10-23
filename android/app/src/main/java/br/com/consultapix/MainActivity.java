package br.com.consultapix;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.net.ssl.SSLException;

public final class MainActivity extends Activity {
    private static final int BG = Color.rgb(243, 246, 245);
    private static final int INK = Color.rgb(24, 60, 53);
    private static final int MUTED = Color.rgb(82, 109, 102);
    private static final int GREEN = Color.rgb(24, 113, 90);
    private static final int SOFT_GREEN = Color.rgb(237, 247, 239);
    private static final String ENDPOINT = "https://api.asaas.com/v3/pix/addressKeys/external";
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler clock = new Handler(Looper.getMainLooper());
    private EditText tokenInput, keyInput;
    private Spinner typeInput;
    private Button saveButton, queryButton;
    private TextView status, cooldown, resultText;
    private LinearLayout resultBox;
    private ProgressBar progress;
    private TokenStore tokenStore;
    private List<Long> queryHistory = new ArrayList<>();
    private boolean busy, historyAvailable = true;
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (isFinishing() || isDestroyed()) return;
            updateButton();
            clock.postDelayed(this, 500L);
        }
    };

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        tokenStore = new TokenStore(this);
        buildUi();
        try {
            queryHistory = tokenStore.loadHistory();
            String token = tokenStore.load();
            if (!token.isEmpty()) {
                tokenInput.setText(token);
                status.setText("Token salvo carregado. Pronto para consultar.");
            }
        } catch (Exception ignored) {
            historyAvailable = false;
            status.setText("Não foi possível ler o cache. Reinicie o aplicativo para tentar novamente.");
        }
        clock.post(tick);
    }

    private TextView text(String value, float size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private GradientDrawable background(int color, int border) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(10));
        if (border != 0) drawable.setStroke(dp(1), border);
        return drawable;
    }

    private LinearLayout.LayoutParams rowParams(int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(top);
        return params;
    }

    private EditText entry(boolean password) {
        EditText edit = new EditText(this);
        edit.setSingleLine(true);
        edit.setTextSize(16);
        edit.setTextColor(INK);
        edit.setPadding(dp(12), dp(12), dp(12), dp(12));
        edit.setBackground(background(Color.WHITE, Color.rgb(170, 188, 181)));
        edit.setSaveEnabled(false);
        edit.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        if (password) {
            edit.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            edit.setTransformationMethod(PasswordTransformationMethod.getInstance());
        }
        return edit;
    }

    private Button button(String title, boolean primary) {
        Button button = new Button(this);
        button.setText(title);
        button.setAllCaps(false);
        button.setTextSize(16);
        button.setMinHeight(dp(48));
        button.setTextColor(primary ? Color.WHITE : GREEN);
        button.setBackground(background(primary ? GREEN : Color.rgb(226, 236, 231), 0));
        button.setPadding(dp(14), dp(8), dp(14), dp(8));
        return button;
    }

    private void buildUi() {
        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.VERTICAL);
        outer.setBackgroundColor(BG);
        outer.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        outer.addView(scroll, new LinearLayout.LayoutParams(-1, -1));
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(22), dp(24), dp(22), dp(22));
        scroll.addView(body, new ScrollView.LayoutParams(-1, -2));
        body.addView(text("Consultar Pix", 28, INK, true));
        body.addView(text("Uma chave por vez", 14, MUTED, false), rowParams(5));

        LinearLayout tokenLabelRow = new LinearLayout(this);
        tokenLabelRow.setGravity(Gravity.CENTER_VERTICAL);
        tokenLabelRow.addView(text("Token", 15, INK, true), new LinearLayout.LayoutParams(0, -2, 1));
        CheckBox show = new CheckBox(this);
        show.setText("Mostrar");
        show.setTextSize(13);
        show.setTextColor(MUTED);
        tokenLabelRow.addView(show);
        body.addView(tokenLabelRow, rowParams(24));
        LinearLayout tokenRow = new LinearLayout(this);
        tokenRow.setGravity(Gravity.CENTER_VERTICAL);
        tokenInput = entry(true);
        tokenInput.setHint("Cole seu token de produção");
        tokenRow.addView(tokenInput, new LinearLayout.LayoutParams(0, -2, 1));
        saveButton = button("Salvar", false);
        LinearLayout.LayoutParams saveParams = new LinearLayout.LayoutParams(-2, dp(48));
        saveParams.leftMargin = dp(8);
        tokenRow.addView(saveButton, saveParams);
        body.addView(tokenRow, rowParams(2));
        body.addView(text("Salvar lembra o token neste aparelho.", 12, MUTED, false), rowParams(6));
        show.setOnCheckedChangeListener((button, checked) -> {
            tokenInput.setTransformationMethod(checked ? null : PasswordTransformationMethod.getInstance());
            tokenInput.setSelection(tokenInput.getText().length());
        });
        saveButton.setOnClickListener(view -> saveToken());

        body.addView(text("Tipo de chave", 15, INK, true), rowParams(23));
        typeInput = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, PixCore.TYPE_LABELS);
        typeInput.setAdapter(adapter);
        typeInput.setBackground(background(Color.WHITE, Color.rgb(170, 188, 181)));
        typeInput.setMinimumHeight(dp(48));
        typeInput.setPadding(dp(8), 0, dp(8), 0);
        body.addView(typeInput, rowParams(7));
        body.addView(text("Chave Pix", 15, INK, true), rowParams(17));
        keyInput = entry(false);
        keyInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        keyInput.setHint("Digite a chave que deseja consultar");
        keyInput.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        body.addView(keyInput, rowParams(7));
        queryButton = button("Consultar", true);
        body.addView(queryButton, rowParams(20));
        queryButton.setOnClickListener(view -> query());
        keyInput.setOnEditorActionListener((view, action, event) -> {
            if (action == EditorInfo.IME_ACTION_SEARCH) { query(); return true; }
            return false;
        });
        cooldown = text("Uma consulta a cada 30 segundos.", 12, MUTED, false);
        body.addView(cooldown, rowParams(8));
        status = text("Pronto para consultar.", 13, MUTED, false);
        body.addView(status, rowParams(12));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true);
        progress.setVisibility(View.GONE);
        body.addView(progress, rowParams(8));
        body.addView(text("Resultado", 16, INK, true), rowParams(23));
        resultBox = new LinearLayout(this);
        resultBox.setOrientation(LinearLayout.VERTICAL);
        resultBox.setPadding(dp(16), dp(16), dp(16), dp(16));
        resultBox.setBackground(background(Color.WHITE, Color.rgb(206, 218, 212)));
        resultText = text("O retorno da consulta aparecerá aqui.", 15, INK, false);
        resultText.setTextIsSelectable(true);
        resultText.setMinHeight(dp(130));
        resultBox.addView(resultText, new LinearLayout.LayoutParams(-1, -2));
        body.addView(resultBox, rowParams(9));
        body.addView(text("Somente consulta. Nenhuma transferência é realizada.", 12, MUTED, false), rowParams(18));
        setContentView(outer);
        outer.requestApplyInsets();
    }

    private void saveToken() {
        if (busy) return;
        String value = tokenInput.getText().toString().trim();
        try {
            if (!value.isEmpty()) value = PixCore.normalizeToken(value);
            tokenStore.save(value);
            if (!historyAvailable) {
                queryHistory = tokenStore.loadHistory();
                historyAvailable = true;
            }
            status.setText(value.isEmpty() ? "Token salvo removido." : "Token salvo neste aparelho.");
            status.setTextColor(GREEN);
        } catch (PixCore.InputError error) {
            status.setText(error.getMessage());
            status.setTextColor(Color.rgb(153, 63, 42));
        } catch (Exception ignored) {
            status.setText("Não foi possível salvar o token ou acessar o cache neste aparelho.");
            status.setTextColor(Color.rgb(153, 63, 42));
        }
        updateButton();
    }

    private void updateButton() {
        if (busy) {
            queryButton.setEnabled(false);
            queryButton.setText("Consultando…");
            return;
        }
        long remaining = PixCore.waitMillis(queryHistory, System.currentTimeMillis());
        boolean available = historyAvailable && remaining == 0L;
        queryButton.setEnabled(available);
        queryButton.setAlpha(available ? 1f : 0.6f);
        queryButton.setText(!historyAvailable ? "Cache indisponível" : remaining > 0L ? "Aguarde " + PixCore.countdown(remaining) : "Consultar");
        cooldown.setText(remaining > 0L ? "Próxima consulta em " + PixCore.countdown(remaining) + "." : "Uma consulta a cada 30 segundos.");
    }

    private void setBusy(boolean value) {
        busy = value;
        saveButton.setEnabled(!value);
        tokenInput.setEnabled(!value);
        keyInput.setEnabled(!value);
        typeInput.setEnabled(!value);
        progress.setVisibility(value ? View.VISIBLE : View.GONE);
        updateButton();
    }

    private void query() {
        if (busy || !historyAvailable) return;
        final String token, key, type;
        try {
            token = PixCore.normalizeToken(tokenInput.getText().toString());
            type = PixCore.TYPES[typeInput.getSelectedItemPosition()];
            key = PixCore.normalizeKey(type, keyInput.getText().toString());
        } catch (PixCore.InputError error) {
            status.setText(error.getMessage());
            status.setTextColor(Color.rgb(153, 63, 42));
            return;
        }
        try {
            long now = System.currentTimeMillis();
            queryHistory = tokenStore.loadHistory();
            if (PixCore.waitMillis(queryHistory, now) > 0L) { updateButton(); return; }
            queryHistory = PixCore.recentQueries(queryHistory, now);
            queryHistory.add(now);
            tokenStore.saveHistory(queryHistory);
        } catch (Exception ignored) {
            historyAvailable = false;
            status.setText("Não foi possível registrar a consulta no cache. Nenhuma consulta foi enviada.");
            status.setTextColor(Color.rgb(153, 63, 42));
            updateButton();
            return;
        }
        InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(keyInput.getWindowToken(), 0);
        setBusy(true);
        status.setText("Consultando…");
        status.setTextColor(MUTED);
        resultText.setText("Consultando a chave informada…");
        resultText.setTextColor(INK);
        resultBox.setBackground(background(Color.WHITE, Color.rgb(206, 218, 212)));
        worker.execute(() -> {
            ApiResult result = fetch(token, type, key);
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                setBusy(false);
                resultText.setText(PixCore.sanitize(result.message, token));
                if (result.kind == 1) {
                    resultBox.setBackground(background(SOFT_GREEN, Color.rgb(182, 216, 194)));
                    resultText.setTextColor(Color.rgb(77, 130, 104));
                    status.setText("Consulta concluída: chave não cadastrada.");
                    status.setTextColor(Color.rgb(77, 130, 104));
                } else if (result.kind == 0) {
                    resultBox.setBackground(background(Color.WHITE, Color.rgb(206, 218, 212)));
                    resultText.setTextColor(INK);
                    status.setText("Consulta concluída.");
                    status.setTextColor(GREEN);
                } else {
                    resultBox.setBackground(background(Color.rgb(255, 247, 235), Color.rgb(226, 210, 181)));
                    resultText.setTextColor(Color.rgb(124, 79, 36));
                    status.setText("Consulta não concluída. Veja o motivo abaixo.");
                    status.setTextColor(Color.rgb(124, 79, 36));
                }
            });
        });
    }

    private static final class ApiResult {
        final int kind;
        final String message;
        ApiResult(int kind, String message) { this.kind = kind; this.message = message; }
    }

    private ApiResult fetch(String token, String type, String key) {
        HttpURLConnection connection = null;
        try {
            String query = "?type=" + URLEncoder.encode(type, "UTF-8") + "&key=" + URLEncoder.encode(key, "UTF-8");
            connection = (HttpURLConnection) new URL(ENDPOINT + query).openConnection();
            connection.setRequestMethod("GET");
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(20000);
            connection.setReadTimeout(20000);
            connection.setRequestProperty("access_token", token);
            connection.setRequestProperty("User-Agent", "ConsultaPixAndroid/1.5");
            connection.setRequestProperty("Accept", "application/json");
            int http = connection.getResponseCode();
            InputStream stream = http >= 400 ? connection.getErrorStream() : connection.getInputStream();
            String body = readBody(stream);
            JSONObject data = null;
            try { data = new JSONObject(body); } catch (JSONException ignored) { }
            List<PixCore.ApiError> errors = errors(data);
            if (http >= 200 && http < 300 && data != null && data.length() > 0 && errors.isEmpty())
                return new ApiResult(0, format(data));
            if ((http == 400 || http == 404) && PixCore.isExplicitMissing(http, errors))
                return new ApiResult(1, PixCore.missingMessage(type) + "\n\nA resposta do serviço confirmou que esta chave não está cadastrada.\n\nHTTP " + http);
            if (http >= 200 && http < 300) {
                if (!errors.isEmpty()) return new ApiResult(2, PixCore.errorMessage(400, errors));
                return new ApiResult(2, "O serviço retornou uma resposta inesperada. Não foi possível confirmar a situação da chave.");
            }
            return new ApiResult(2, PixCore.errorMessage(http, errors));
        } catch (SocketTimeoutException error) {
            return new ApiResult(2, "A consulta demorou para responder. Confira a conexão e tente novamente.");
        } catch (SSLException error) {
            return new ApiResult(2, "Não foi possível validar a conexão segura. Confira a data e a conexão do aparelho.");
        } catch (Exception error) {
            return new ApiResult(2, "Não foi possível concluir a consulta. Confira sua internet e tente novamente.");
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private String readBody(InputStream stream) throws Exception {
        if (stream == null) return "";
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > PixCore.MAX_RESPONSE) throw new Exception("Resposta grande demais.");
                output.write(buffer, 0, count);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private List<PixCore.ApiError> errors(JSONObject data) {
        List<PixCore.ApiError> list = new ArrayList<>();
        if (data == null) return list;
        JSONArray values = data.optJSONArray("errors");
        if (values != null) {
            for (int i = 0; i < Math.min(values.length(), 10); i++) {
                JSONObject error = values.optJSONObject(i);
                if (error != null) list.add(new PixCore.ApiError(error.optString("code", ""), error.optString("description", "")));
            }
        }
        if (list.isEmpty() && data.has("description"))
            list.add(new PixCore.ApiError(data.optString("code", ""), data.optString("description", "")));
        if (list.isEmpty() && data.has("message"))
            list.add(new PixCore.ApiError(data.optString("code", ""), data.optString("message", "")));
        return list;
    }

    private String format(JSONObject data) throws JSONException {
        StringBuilder result = new StringBuilder();
        JSONObject owner = data.optJSONObject("owner");
        JSONObject bank = data.optJSONObject("financialInstitution");
        append(result, "Titular", owner == null ? data.optString("ownerName", data.optString("name", "")) : owner.optString("name", ""));
        append(result, "CPF/CNPJ", owner == null ? data.optString("cpfCnpj", "") : owner.optString("cpfCnpj", ""));
        append(result, "Instituição", bank == null ? data.optString("ispbName", "") : bank.optString("name", ""));
        append(result, "Código do banco", bank == null ? "" : bank.optString("code", ""));
        append(result, "Chave", data.optString("key", ""));
        append(result, "Tipo", data.optString("type", ""));
        if (result.length() > 0) result.append("Resposta completa\n\n");
        return result.append(data.toString(2)).toString();
    }

    private void append(StringBuilder result, String label, String value) {
        if (!value.isEmpty() && !"null".equals(value)) result.append(label).append("\n").append(value).append("\n\n");
    }

    @Override protected void onDestroy() {
        clock.removeCallbacks(tick);
        worker.shutdownNow();
        super.onDestroy();
    }
}
