# Admin-created Personal Vehicle Owner checklist

- As Admin, create an active Personal Vehicle Owner with unique email, phone, and temporary password.
- Confirm duplicate email and duplicate phone are rejected.
- Confirm the account row shows status, created date, last login, and password-change requirement without a database ID.
- Sign in with the temporary password and confirm only `/change-password` is available.
- Change the password, confirm `/my-vehicles/dashboard` opens, then sign out and sign in with the new password.
- Edit the personal user's name, phone, and email as Admin.
- Reset the temporary password and confirm first-login enforcement returns.
- Deactivate the account and confirm login is denied; reactivate it and confirm login succeeds.
- Confirm the personal account receives 403 from Admin, Driver, Fleet Owner, dispatch, reports, and other commercial APIs.
- Recheck existing Owner, Admin, Driver, and Fleet Owner login and user-management paths.
