package br.com.consultapix;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Properties;
import java.util.ArrayList;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Save writes an encrypted INI only inside the app-private files directory. */
public final class TokenStore {
    private static final String ALIAS = "consulta_pix_token_v1";
    private final Context context;

    public TokenStore(Context context) { this.context = context.getApplicationContext(); }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(ALIAS)) return (SecretKey) store.getKey(ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build());
        return generator.generateKey();
    }

    private synchronized Properties readProperties() throws Exception {
        File file = new File(context.getFilesDir(), "cache.ini");
        Properties ini = new Properties();
        if (!file.exists()) return ini;
        if (file.length() > 16384) throw new Exception("Cache inválido.");
        try (FileInputStream input = new FileInputStream(file)) { ini.load(input); }
        return ini;
    }

    public synchronized String load() throws Exception {
        Properties ini = readProperties();
        String iv = ini.getProperty("iv", "");
        String token = ini.getProperty("token_encrypted", "");
        if (iv.isEmpty() && token.isEmpty()) return "";
        if (iv.isEmpty() || token.isEmpty()) throw new Exception("Cache inválido.");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(token, Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }

    public synchronized void save(String token) throws Exception {
        Properties ini = readProperties();
        if (token.isEmpty()) {
            ini.remove("iv");
            ini.remove("token_encrypted");
            writeProperties(ini);
            return;
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] encrypted = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        ini.setProperty("version", "1");
        ini.setProperty("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP));
        ini.setProperty("token_encrypted", Base64.encodeToString(encrypted, Base64.NO_WRAP));
        writeProperties(ini);
    }

    public synchronized List<Long> loadHistory() throws Exception {
        Properties ini = readProperties();
        String history = ini.getProperty("queries", "");
        List<Long> values = new ArrayList<>();
        if (history.isEmpty()) return values;
        String[] entries = history.split(",", -1);
        if (entries.length > 2) throw new Exception("Histórico inválido.");
        for (String entry : entries) {
            long timestamp = Long.parseLong(entry);
            if (timestamp <= 0) throw new Exception("Histórico inválido.");
            values.add(timestamp);
        }
        return values;
    }

    public synchronized void saveHistory(List<Long> history) throws Exception {
        Properties ini = readProperties();
        StringBuilder data = new StringBuilder();
        for (Long timestamp : history) {
            if (data.length() > 0) data.append(',');
            data.append(timestamp);
        }
        ini.setProperty("queries", data.toString());
        writeProperties(ini);
    }

    private void writeProperties(Properties ini) throws Exception {
        StringBuilder data = new StringBuilder("[consulta_pix]\nversion=1\n");
        for (String name : new String[]{"iv", "token_encrypted", "queries"}) {
            String value = ini.getProperty(name);
            if (value != null) data.append(name).append('=').append(value).append('\n');
        }
        File temp = new File(context.getFilesDir(), "cache.ini.tmp");
        try (FileOutputStream output = context.openFileOutput(temp.getName(), Context.MODE_PRIVATE)) {
            output.write(data.toString().getBytes(StandardCharsets.US_ASCII));
            output.getFD().sync();
        }
        File destination = new File(context.getFilesDir(), "cache.ini");
        if (!temp.renameTo(destination)) {
            temp.delete();
            throw new Exception("Não foi possível salvar o cache.");
        }
    }
}
