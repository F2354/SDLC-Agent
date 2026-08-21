param(
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$Username = 'demo',
    [string]$Password = 'demo123456',
    [string]$ProjectName = '在线考试系统'
)

$ErrorActionPreference = 'Stop'

$login = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/auth/login" -ContentType 'application/json' -Body (@{ username = $Username; password = $Password } | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($login.access_token)" }

$providers = @(Invoke-RestMethod -Uri "$BaseUrl/api/providers" -Headers $headers)
if ($providers.Count -eq 0) {
    throw '当前账号没有可用的模型 Provider，请先在模型服务页面配置。'
}
$providerId = [int]$providers[0].id

$project = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/projects" -Headers $headers -ContentType 'application/json' -Body (@{
    name = $ProjectName
    description = 'M7 完整案例验证'
    process_model_code = 'waterfall'
} | ConvertTo-Json)
$projectId = [int]$project.id

$stageCodes = @('requirements', 'architecture', 'detailed-design', 'coding', 'testing')
$summary = @()

foreach ($code in $stageCodes) {
    $run = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/projects/$projectId/stages/$code/start" -Headers $headers -ContentType 'application/json' -Body (@{
        mode = 'auto'
        provider_id = $providerId
    } | ConvertTo-Json)

    $status = $run.status
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 3
        $flow = Invoke-RestMethod -Uri "$BaseUrl/api/projects/$projectId/flow" -Headers $headers
        $item = @($flow.stages | Where-Object { $_.stage.code -eq $code })[0]
        $status = $item.status
        if ($status -in @('awaiting_review', 'failed', 'approved')) {
            break
        }
    }

    if ($status -eq 'awaiting_review') {
        $approved = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/stage-runs/$($run.id)/approve" -Headers $headers -ContentType 'application/json' -Body (@{ comment = 'M7 自动验证通过' } | ConvertTo-Json)
        $status = $approved.status
    }
    $summary += "$code=$status"
}

$finalFlow = Invoke-RestMethod -Uri "$BaseUrl/api/projects/$projectId/flow" -Headers $headers
$stats = Invoke-RestMethod -Uri "$BaseUrl/api/projects/$projectId/stats" -Headers $headers

Write-Host "projectId=$projectId"
Write-Host "result=$($summary -join ' ')"
Write-Host "artifacts=$($stats.artifact_count) chars=$($stats.total_chars) trace=$($stats.entity_counts | ConvertTo-Json -Compress)"
