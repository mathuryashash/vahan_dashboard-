import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended, jsxA11y.flatConfigs.recommended],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Existing codebase makes heavy, deliberate use of untyped API
      // response shapes (see api/vahan.ts) -- enabling this would mean
      // hundreds of pre-existing findings unrelated to hook/a11y bugs,
      // which is what this config exists to catch.
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      // Accessibility gaps are real but pre-existing across most of this
      // codebase (see the frontend review) -- warn so they're visible in
      // `npm run lint` and new violations get caught in review, without
      // making every existing page a hard lint failure on day one.
      ...Object.fromEntries(
        Object.keys(jsxA11y.flatConfigs.recommended.rules).map((rule) => [rule, 'warn']),
      ),
    },
  },
)
