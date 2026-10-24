package com.interactive.brasiliptv.app;

import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import core.request.converterFactory.bean.ResultException;
import core.request.result.ActiveResult;
import core.request.result.LoginResult;
import io.reactivex.Observable;
import io.reactivex.ObservableSource;
import io.reactivex.functions.Function;
import io.reactivex.functions.Consumer;
import io.reactivex.schedulers.Schedulers;
import io.reactivex.subjects.ReplaySubject;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** One background authentication attempt shared by failed catalog requests. */
@SuppressWarnings({"rawtypes", "unchecked"})
public final class SilentRefresh {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final Set<String> READS = new HashSet<String>(Arrays.asList(
        "GetItemDataBean", "GetItemDataByLangBean", "GetRecommendsBean",
        "GetColumnContentsBean", "FilterGenreBean", "StartPlayVODBean",
        "EpgBean", "LineupBean", "GetPersonBean", "ItemByPersonBean"));
    private static Flight current;
    private static long lastAttempt = -60000L;

    public static void onRemoteSessionEvent() {
        String token = zc.f0.a.n();
        String id = zc.f0.a.o();
        if (token == null || token.length() == 0 || id == null || id.length() == 0) return;
        refresh().subscribe(new Consumer<Boolean>() {
            @Override public void accept(Boolean ok) { }
        }, new Consumer<Throwable>() {
            @Override public void accept(Throwable failure) {
                Log.i("UniTVSession", "remote session recovery not completed or cooldown active");
            }
        });
    }

    public static Observable wrap(final Observable source, final Object bean,
                                  final Function request) {
        if (bean == null || !READS.contains(bean.getClass().getSimpleName())) return source;
        final String sentToken = read(bean, "getUserToken");
        if (sentToken.length() == 0 || read(bean, "getUserId").length() == 0) return source;
        Observable checked = source.flatMap(new Function<Object, ObservableSource>() {
            @Override public ObservableSource apply(Object response) {
                String code = read(response, "getReturnCode");
                if (sessionCode(code))
                    return Observable.error(new ResultException(code, "Session response requires refresh"));
                return Observable.just(response);
            }
        });
        return checked.onErrorResumeNext(new Function<Throwable, ObservableSource>() {
            @Override public ObservableSource apply(final Throwable original) {
                if (!sessionError(original)) return Observable.error(original);
                final String token = zc.f0.a.n();
                if (token == null || token.length() == 0) return Observable.error(original);
                Observable<Boolean> ready = token != null && token.length() != 0
                        && !token.equals(sentToken)
                    ? Observable.just(Boolean.TRUE) : refresh();
                return ready.onErrorResumeNext(new Function<Throwable, ObservableSource<Boolean>>() {
                    @Override public ObservableSource<Boolean> apply(Throwable failure) {
                        return Observable.error(original);
                    }
                }).flatMap(new Function<Boolean, ObservableSource<Object>>() {
                    @Override public ObservableSource<Object> apply(Boolean ok) {
                        return replay(bean, request);
                    }
                });
            }
        });
    }

    private static Observable replay(final Object bean, final Function request) {
        return Observable.defer(new java.util.concurrent.Callable<ObservableSource<Object>>() {
            @Override public ObservableSource<Object> call() throws Exception {
                String id = zc.f0.a.o();
                String token = zc.f0.a.n();
                if (id == null || id.length() == 0 || token == null || token.length() == 0)
                    throw new IllegalStateException("Session credentials unavailable");
                bean.getClass().getMethod("setUserId", String.class).invoke(bean, id);
                bean.getClass().getMethod("setUserToken", String.class).invoke(bean, token);
                Log.i("UniTVSession", "retrying catalog request once after session recovery");
                return (ObservableSource) request.apply(bean);
            }
        }).subscribeOn(Schedulers.io());
    }

    private static String read(Object bean, String getter) {
        try {
            Method method = bean.getClass().getMethod(getter);
            Object value = method.invoke(bean);
            return value instanceof String ? (String) value : "";
        } catch (Exception ignored) { return ""; }
    }

    private static boolean sessionError(Throwable failure) {
        for (int i = 0; failure != null && i < 4; i++, failure = failure.getCause()) {
            if (failure instanceof ResultException) {
                String code = ((ResultException) failure).getReturnCode();
                return sessionCode(code);
            }
        }
        return false;
    }

    private static boolean sessionCode(String code) {
        return "aaa100027".equals(code) || "aaa100028".equals(code)
            || "aaa100083".equals(code) || "portal100054".equals(code);
    }

    private static synchronized Observable<Boolean> refresh() {
        if (current != null) return current.result.hide();
        long now = SystemClock.elapsedRealtime();
        if (now - lastAttempt < 60000L)
            return Observable.error(new IllegalStateException("Session recovery cooldown"));
        lastAttempt = now;
        final Flight flight = new Flight();
        current = flight;
        MAIN.post(new Runnable() {
            @Override public void run() {
                synchronized (SilentRefresh.class) {
                    if (current != flight || flight.finished) return;
                }
                String token = zc.f0.a.n();
                if (token == null || token.length() == 0) {
                    finish(flight, false);
                    return;
                }
                Log.i("UniTVSession", "starting shared background session recovery");
                MAIN.postDelayed(flight.timeout, 12000L);
                try { yb.h.a.refreshSilently(flight.callback); }
                catch (Throwable failure) { finish(flight, false); }
            }
        });
        return flight.result.hide();
    }

    private static void finish(final Flight flight, boolean success) {
        synchronized (SilentRefresh.class) {
            if (current != flight || flight.finished) return;
            flight.finished = true;
            current = null;
        }
        MAIN.removeCallbacks(flight.timeout);
        // The original dispatcher iterates its listener list, then clears it.
        // Remove our listener on the next main-loop turn, never during that loop.
        MAIN.post(new Runnable() {
            @Override public void run() { yb.h.a.c1(flight.callback); }
        });
        Log.i("UniTVSession", success ? "background session recovery succeeded"
            : "background session recovery failed or timed out");
        if (success) {
            flight.result.onNext(Boolean.TRUE);
            flight.result.onComplete();
        } else {
            flight.result.onError(new IllegalStateException("Session recovery unsuccessful"));
        }
    }

    private static final class Flight {
        final ReplaySubject<Boolean> result = ReplaySubject.createWithSize(1);
        boolean finished;
        final Runnable timeout = new Runnable() {
            @Override public void run() { finish(Flight.this, false); }
        };
        final yb.h.a callback = new yb.h.a() {
            @Override public void a(boolean success, String code, ActiveResult active,
                                    LoginResult login, String uri) {
                finish(Flight.this, success);
            }
        };
    }
}
