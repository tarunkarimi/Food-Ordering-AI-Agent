import {
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  apiRequest,
  clearAuth,
  getAccessToken,
  getStoredUser,
  saveAuth,
  saveUser,
} from "./auth";

import "./AuthGate.css";

const MODES = {
  LOGIN: "login",
  SIGNUP: "signup",
  VERIFY_SIGNUP: "verify-signup",
  LOGIN_OTP: "login-otp",
};

function getIdentityField(mode, identity) {
  if (identity === "phone") {
    return {
      name: "phone",
      label: "Phone number",
      type: "tel",
      placeholder: "+91 9876543210",
    };
  }

  return {
    name: "email",
    label: "Email address",
    type: "email",
    placeholder: "you@example.com",
  };
}

function getErrorMessage(data, fallback) {
  if (typeof data?.detail === "string") {
    return data.detail;
  }

  if (Array.isArray(data?.detail)) {
    return data.detail
      .map((item) => item?.msg)
      .filter(Boolean)
      .join(", ");
  }

  return fallback;
}

function AuthForm({
  mode,
  identity,
  setIdentity,
  onLogin,
  onSignup,
  onRequestLoginOtp,
  loading,
  error,
}) {
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");

  const identityField = useMemo(
    () => getIdentityField(mode, identity),
    [mode, identity]
  );

  const isSignup = mode === MODES.SIGNUP;
  const isLogin = mode === MODES.LOGIN;

  function submit(event) {
    event.preventDefault();

    const value =
      identity === "email"
        ? email.trim()
        : phone.trim();

    if (!value) {
      return;
    }

    if (isSignup) {
      onSignup({
        email:
          identity === "email"
            ? value
            : undefined,
        phone:
          identity === "phone"
            ? value
            : undefined,
        password,
      });

      return;
    }

    onLogin({
      email:
        identity === "email"
          ? value
          : undefined,
      phone:
        identity === "phone"
          ? value
          : undefined,
      password,
    });
  }

  return (
    <form
      className="auth-form"
      onSubmit={submit}
    >
      <div className="identity-switch">
        <button
          type="button"
          className={
            identity === "email"
              ? "active"
              : ""
          }
          onClick={() => setIdentity("email")}
          disabled={loading}
        >
          Email
        </button>

        <button
          type="button"
          className={
            identity === "phone"
              ? "active"
              : ""
          }
          onClick={() => setIdentity("phone")}
          disabled={loading}
        >
          Phone
        </button>
      </div>

      <label>
        <span>{identityField.label}</span>

        <input
          type={identityField.type}
          value={
            identity === "email"
              ? email
              : phone
          }
          onChange={(event) =>
            identity === "email"
              ? setEmail(event.target.value)
              : setPhone(event.target.value)
          }
          placeholder={
            identityField.placeholder
          }
          autoComplete={
            identity === "email"
              ? "email"
              : "tel"
          }
          disabled={loading}
          required
        />
      </label>

      <label>
        <span>Password</span>

        <input
          type="password"
          value={password}
          onChange={(event) =>
            setPassword(event.target.value)
          }
          placeholder="Minimum 8 characters"
          autoComplete={
            isSignup
              ? "new-password"
              : "current-password"
          }
          minLength={8}
          disabled={loading}
          required
        />
      </label>

      {error && (
        <div className="auth-error">
          {error}
        </div>
      )}

      <button
        className="auth-primary-button"
        type="submit"
        disabled={
          loading ||
          !password ||
          (identity === "email"
            ? !email.trim()
            : !phone.trim())
        }
      >
        {loading
          ? "Please wait..."
          : isSignup
          ? "Create Account"
          : "Sign In"}
      </button>

      {isLogin && (
        <button
          type="button"
          className="auth-secondary-button"
          disabled={loading}
          onClick={() => {
            const value =
              identity === "email"
                ? email.trim()
                : phone.trim();

            onRequestLoginOtp({
              email:
                identity === "email"
                  ? value
                  : undefined,
              phone:
                identity === "phone"
                  ? value
                  : undefined,
            });
          }}
        >
          Sign in with OTP
        </button>
      )}
    </form>
  );
}

export default function AuthGate({
  children,
}) {
  const [mode, setMode] = useState(
    MODES.LOGIN
  );

  const [identity, setIdentity] =
    useState("email");

  const [user, setUser] = useState(
    getStoredUser
  );

  const [loading, setLoading] =
    useState(Boolean(getAccessToken()));

  const [error, setError] =
    useState("");

  const [verificationUser, setVerificationUser] =
    useState(null);

  const [verificationCode, setVerificationCode] =
    useState("");

  const [loginOtpIdentity, setLoginOtpIdentity] =
    useState(null);

  const [loginOtpCode, setLoginOtpCode] =
    useState("");

  const [checkingSession, setCheckingSession] =
    useState(Boolean(getAccessToken()));

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      const token = getAccessToken();

      if (!token) {
        if (active) {
          setCheckingSession(false);
          setLoading(false);
        }

        return;
      }

      try {
        const response = await apiRequest(
          "/api/auth/me"
        );

        if (!response.ok) {
          throw new Error(
            "Authentication session is no longer valid."
          );
        }

        const authenticatedUser =
          await response.json();

        if (active) {
          saveUser(authenticatedUser);
          setUser(authenticatedUser);
        }
      } catch {
        clearAuth();

        if (active) {
          setUser(null);
        }
      } finally {
        if (active) {
          setCheckingSession(false);
          setLoading(false);
        }
      }
    }

    restoreSession();

    return () => {
      active = false;
    };
  }, []);

  async function handleSignup(payload) {
    setError("");
    setLoading(true);

    try {
      const response = await apiRequest(
        "/api/auth/signup",
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getErrorMessage(
            data,
            "Unable to create your account."
          )
        );
      }

      const channel = payload.email
        ? "email"
        : "phone";

      const verificationResponse =
        await apiRequest(
          "/api/auth/verification/request",
          {
            method: "POST",
            body: JSON.stringify({
              user_id: data.id,
              channel,
              purpose: "signup",
            }),
          }
        );

      const verificationData =
        await verificationResponse.json();

      if (!verificationResponse.ok) {
        throw new Error(
          getErrorMessage(
            verificationData,
            "Account created, but verification could not be started."
          )
        );
      }

      setVerificationUser({
        ...data,
        channel,
      });

      setVerificationCode("");
      setMode(MODES.VERIFY_SIGNUP);
    } catch (requestError) {
      setError(
        requestError?.message ||
          "Unable to create your account."
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleSignupVerification() {
    if (
      !verificationUser ||
      !/^\d{6}$/.test(
        verificationCode.trim()
      )
    ) {
      setError(
        "Enter the 6-digit verification code."
      );
      return;
    }

    setError("");
    setLoading(true);

    try {
      const response = await apiRequest(
        "/api/auth/verification/verify",
        {
          method: "POST",
          body: JSON.stringify({
            user_id: verificationUser.id,
            channel:
              verificationUser.channel,
            purpose: "signup",
            code: verificationCode.trim(),
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getErrorMessage(
            data,
            "Verification failed."
          )
        );
      }

      setVerificationUser(null);
      setVerificationCode("");
      setMode(MODES.LOGIN);
      setError(
        "Verification successful. You can now sign in."
      );
    } catch (requestError) {
      setError(
        requestError?.message ||
          "Verification failed."
      );
    } finally {
      setLoading(false);
    }
  }

  async function resendSignupVerification() {
    if (!verificationUser) {
      return;
    }

    setError("");
    setLoading(true);

    try {
      const response = await apiRequest(
        "/api/auth/verification/request",
        {
          method: "POST",
          body: JSON.stringify({
            user_id: verificationUser.id,
            channel:
              verificationUser.channel,
            purpose: "signup",
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getErrorMessage(
            data,
            "Unable to resend verification code."
          )
        );
      }

      setError(
        "A new verification code has been requested."
      );
    } catch (requestError) {
      setError(
        requestError?.message ||
          "Unable to resend verification code."
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(payload) {
    setError("");
    setLoading(true);

    try {
      const response = await apiRequest(
        "/api/auth/login",
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getErrorMessage(
            data,
            "Unable to sign in."
          )
        );
      }

      saveAuth(data);
      setUser(data.user);
      setError("");
    } catch (requestError) {
      setError(
        requestError?.message ||
          "Unable to sign in."
      );
    } finally {
      setLoading(false);
    }
  }

  async function requestLoginOtp(payload) {
    setError("");

    if (
      !payload.email &&
      !payload.phone
    ) {
      setError(
        "Enter your email or phone number first."
      );
      return;
    }

    setLoading(true);

    try {
      const response = await apiRequest(
        "/api/auth/login/otp/request",
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getErrorMessage(
            data,
            "Unable to start OTP login."
          )
        );
      }

      setLoginOtpIdentity(payload);
      setLoginOtpCode("");
      setMode(MODES.LOGIN_OTP);
    } catch (requestError) {
      setError(
        requestError?.message ||
          "Unable to start OTP login."
      );
    } finally {
      setLoading(false);
    }
  }

  async function verifyLoginOtp() {
    if (
      !loginOtpIdentity ||
      !/^\d{6}$/.test(
        loginOtpCode.trim()
      )
    ) {
      setError(
        "Enter the 6-digit OTP."
      );
      return;
    }

    setError("");
    setLoading(true);

    try {
      const response = await apiRequest(
        "/api/auth/login/otp/verify",
        {
          method: "POST",
          body: JSON.stringify({
            ...loginOtpIdentity,
            code: loginOtpCode.trim(),
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          getErrorMessage(
            data,
            "OTP verification failed."
          )
        );
      }

      saveAuth(data);
      setUser(data.user);
      setLoginOtpIdentity(null);
      setLoginOtpCode("");
      setError("");
    } catch (requestError) {
      setError(
        requestError?.message ||
          "OTP verification failed."
      );
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    setLoading(true);

    try {
      const token = getAccessToken();

      if (token) {
        await apiRequest(
          "/api/auth/logout",
          {
            method: "POST",
          }
        );
      }
    } catch (logoutError) {
      console.error(
        "Logout request failed:",
        logoutError
      );
    } finally {
      clearAuth();
      setUser(null);
      setMode(MODES.LOGIN);
      setVerificationUser(null);
      setLoginOtpIdentity(null);
      setError("");
      setLoading(false);
    }
  }

  if (checkingSession) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">
          <div className="auth-logo">???</div>
          <strong>
            Restoring your session...
          </strong>
          <span>
            Please wait.
          </span>
        </div>
      </div>
    );
  }

  if (user) {
    return (
      <div className="authenticated-app">
        <div className="account-bar">
          <div className="account-info">
            <span className="account-status-dot" />
            <span>
              {user.email ||
                user.phone ||
                "Authenticated user"}
            </span>
          </div>

          <button
            type="button"
            onClick={logout}
            disabled={loading}
          >
            Sign out
          </button>
        </div>

        {children}
      </div>
    );
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-logo">
            ???
          </div>

          <div>
            <h1>FoodAI</h1>
            <p>
              AI-powered food ordering
            </p>
          </div>
        </div>

        {mode === MODES.VERIFY_SIGNUP ? (
          <>
            <div className="auth-heading">
              <h2>
                Verify your account
              </h2>

              <p>
                Enter the 6-digit code sent to
                your{" "}
                {verificationUser?.channel ===
                "email"
                  ? "email address"
                  : "phone number"}
                .
              </p>
            </div>

            <div className="auth-form">
              <label>
                <span>
                  Verification code
                </span>

                <input
                  inputMode="numeric"
                  maxLength={6}
                  value={verificationCode}
                  onChange={(event) =>
                    setVerificationCode(
                      event.target.value
                        .replace(/\D/g, "")
                    )
                  }
                  placeholder="123456"
                  disabled={loading}
                  autoComplete="one-time-code"
                />
              </label>

              {error && (
                <div
                  className={
                    error.includes(
                      "successful"
                    )
                      ? "auth-success"
                      : "auth-error"
                  }
                >
                  {error}
                </div>
              )}

              <button
                className="auth-primary-button"
                type="button"
                onClick={
                  handleSignupVerification
                }
                disabled={
                  loading ||
                  verificationCode.length !==
                    6
                }
              >
                {loading
                  ? "Verifying..."
                  : "Verify Account"}
              </button>

              <button
                type="button"
                className="auth-secondary-button"
                onClick={
                  resendSignupVerification
                }
                disabled={loading}
              >
                Resend Code
              </button>

              <button
                type="button"
                className="auth-link-button"
                onClick={() => {
                  setVerificationUser(
                    null
                  );
                  setVerificationCode("");
                  setError("");
                  setMode(MODES.LOGIN);
                }}
                disabled={loading}
              >
                Back to Sign In
              </button>
            </div>
          </>
        ) : mode === MODES.LOGIN_OTP ? (
          <>
            <div className="auth-heading">
              <h2>
                Sign in with OTP
              </h2>

              <p>
                Enter the 6-digit code sent to
                your{" "}
                {loginOtpIdentity?.email
                  ? "email address"
                  : "phone number"}
                .
              </p>
            </div>

            <div className="auth-form">
              <label>
                <span>
                  One-time password
                </span>

                <input
                  inputMode="numeric"
                  maxLength={6}
                  value={loginOtpCode}
                  onChange={(event) =>
                    setLoginOtpCode(
                      event.target.value
                        .replace(/\D/g, "")
                    )
                  }
                  placeholder="123456"
                  disabled={loading}
                  autoComplete="one-time-code"
                />
              </label>

              {error && (
                <div className="auth-error">
                  {error}
                </div>
              )}

              <button
                className="auth-primary-button"
                type="button"
                onClick={verifyLoginOtp}
                disabled={
                  loading ||
                  loginOtpCode.length !==
                    6
                }
              >
                {loading
                  ? "Verifying..."
                  : "Verify & Sign In"}
              </button>

              <button
                type="button"
                className="auth-link-button"
                onClick={() => {
                  setLoginOtpIdentity(null);
                  setLoginOtpCode("");
                  setError("");
                  setMode(MODES.LOGIN);
                }}
                disabled={loading}
              >
                Back to Password Login
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="auth-heading">
              <h2>
                {mode === MODES.LOGIN
                  ? "Welcome back"
                  : "Create your account"}
              </h2>

              <p>
                {mode === MODES.LOGIN
                  ? "Sign in to continue ordering with FoodAI."
                  : "Create an account to keep your cart and orders tied to you."}
              </p>
            </div>

            <AuthForm
              mode={mode}
              identity={identity}
              setIdentity={setIdentity}
              onLogin={handleLogin}
              onSignup={handleSignup}
              onRequestLoginOtp={
                requestLoginOtp
              }
              loading={loading}
              error={error}
            />

            <div className="auth-switch">
              {mode === MODES.LOGIN ? (
                <>
                  <span>
                    Don't have an account?
                  </span>

                  <button
                    type="button"
                    onClick={() => {
                      setMode(
                        MODES.SIGNUP
                      );
                      setError("");
                    }}
                  >
                    Create account
                  </button>
                </>
              ) : (
                <>
                  <span>
                    Already have an account?
                  </span>

                  <button
                    type="button"
                    onClick={() => {
                      setMode(
                        MODES.LOGIN
                      );
                      setError("");
                    }}
                  >
                    Sign in
                  </button>
                </>
              )}
            </div>

            {error &&
              mode === MODES.LOGIN &&
              error.includes(
                "Verification successful"
              ) && (
                <div className="auth-success">
                  {error}
                </div>
              )}
          </>
        )}
      </div>
    </div>
  );
}
