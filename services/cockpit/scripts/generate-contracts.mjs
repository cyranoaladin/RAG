import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { compile } from 'json-schema-to-typescript'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const cockpitRoot = path.resolve(scriptDir, '..')
const schemaRoot = path.resolve(cockpitRoot, '../../packages/contracts/schema')
const artifactRoot = path.resolve(cockpitRoot, '../../packages/contracts/src/nexus_contracts/artifacts')
const generatedRoot = path.resolve(cockpitRoot, 'src/generated')
const schemaOutputRoot = path.join(generatedRoot, 'schema')
const check = process.argv.includes('--check')

const schemas = [
  ['retrieval-request.json', 'RetrievalRequest'],
  ['retrieval-response.json', 'RetrievalResponse'],
  ['search-payload.json', 'SearchPayload'],
  ['chat-payload.json', 'ChatPayload'],
  ['chat-request.json', 'ChatRequest'],
  ['chat-response.json', 'ChatResponse'],
  ['internal-identity.json', 'InternalIdentity'],
  ['internal-identity-envelope.json', 'InternalIdentityEnvelope'],
  ['pilot-retrieval-scope-artifact.json', 'PilotRetrievalScopeArtifact'],
  ['retrieval-scope-artifact-v2.json', 'RetrievalScopeArtifactV2'],
  ['review-queue-payload.json', 'ReviewQueuePayload'],
  ['review-decision-payload.json', 'ReviewDecisionPayload'],
  ['review-decision-request.json', 'ReviewDecisionRequest'],
  ['review-queue-response.json', 'ReviewQueueResponse'],
  ['review-decision-response.json', 'ReviewDecisionResponse'],
]

async function readSchemas() {
  return Promise.all(schemas.map(async ([filename, name]) => ({
    filename,
    name,
    schema: JSON.parse(await readFile(path.join(schemaRoot, filename), 'utf8')),
  })))
}

function aggregateSchema(entries) {
  const definitions = {}
  for (const { schema } of entries) {
    for (const [name, definition] of Object.entries(schema.$defs ?? {})) {
      const existing = definitions[name]
      if (existing && JSON.stringify(existing) !== JSON.stringify(definition)) {
        throw new Error(`Schéma incompatible pour la définition partagée ${name}`)
      }
      definitions[name] = definition
    }
    const root = { ...schema }
    delete root.$defs
    delete root.$schema
    delete root.$id
    definitions[schema.title] = root
  }
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $defs: definitions,
    anyOf: entries.map(({ schema }) => ({ $ref: `#/$defs/${schema.title}` })),
  }
}

async function expectedOutputs() {
  const entries = await readSchemas()
  const pilotScope = JSON.parse(await readFile(path.join(artifactRoot, 'pilot-retrieval-scope-v1.json'), 'utf8'))
  const typeSource = await compile(aggregateSchema(entries), 'ContractBundle', {
    bannerComment: '// Generated from packages/contracts/schema. Do not edit manually.\n',
    style: { singleQuote: true },
  })
  const validatorNames = [
    'RetrievalRequest',
    'RetrievalResponse',
    'SearchPayload',
    'ChatPayload',
    'ChatRequest',
    'ChatResponse',
    'InternalIdentity',
    'InternalIdentityEnvelope',
    'PilotRetrievalScopeArtifact',
    'RetrievalScopeArtifactV2',
    'ReviewQueuePayload',
    'ReviewDecisionPayload',
    'ReviewDecisionRequest',
    'ReviewQueueResponse',
    'ReviewDecisionResponse',
  ]
  const validationEntries = entries.filter(({ name }) => validatorNames.includes(name))
  const imports = validationEntries.map(({ filename, name }) =>
    `import ${name}Schema from './schema/${filename}'`,
  ).join('\n')
  const compilers = validationEntries.map(({ name }) =>
    `const ${name[0].toLowerCase()}${name.slice(1)}Validator = ajv.compile<${name}>(${name}Schema)`,
  ).join('\n')
  const validate = validatorNames.map((name) => {
    const variable = `${name[0].toLowerCase()}${name.slice(1)}Validator`
    const semanticCheck = name === 'ReviewQueueResponse'
      ? ' && payload.returned === payload.documents.length'
      : ''
    return `export const validate${name} = (payload: unknown): payload is ${name} => ${variable}(payload) === true${semanticCheck}`
  }).join('\n\n')
  const validatorSource = `// Generated from packages/contracts/schema. Do not edit manually.\nimport Ajv2020 from 'ajv/dist/2020.js'\nimport addFormats from 'ajv-formats'\n\nimport type { ${validationEntries.map(({ name }) => name).join(', ')} } from './contracts'\n${imports}\n\nconst ajv = new Ajv2020({ allErrors: true, strict: false })\naddFormats(ajv)\n${compilers}\n\n${validate}\n`
  return new Map([
    [path.join(generatedRoot, 'contracts.ts'), typeSource],
    [path.join(generatedRoot, 'validators.ts'), validatorSource],
    [path.join(generatedRoot, 'pilot-retrieval-scope-v1.json'), `${JSON.stringify(pilotScope, null, 2)}\n`],
    ...entries.map(({ filename, schema }) => [path.join(schemaOutputRoot, filename), `${JSON.stringify(schema, null, 2)}\n`]),
  ])
}

async function main() {
  const outputs = await expectedOutputs()
  if (check) {
    for (const [filename, contents] of outputs) {
      try {
        if (await readFile(filename, 'utf8') !== contents) process.exitCode = 1
      } catch {
        process.exitCode = 1
      }
    }
    return
  }
  for (const [filename, contents] of outputs) {
    await mkdir(path.dirname(filename), { recursive: true })
    await writeFile(filename, contents)
  }
}

await main()
